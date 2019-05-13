import itertools

import flexiblekernel as fk


ONE_D_RULES = [('A', ('+', 'A', 'B'), {'A': 'any', 'B': 'base'}),        # replace with K plus a base kernel
               ('A', ('*', 'A', 'B'), {'A': 'any', 'B': 'base'}),        # replace with K times a base kernel
               ('A', 'B', {'A': 'base', 'B': 'base'}),                   # replace one base kernel with another
               ]

#### FIXME - Code duplication - do we need the OneDGrammar as a special case - else remove
class OneDGrammar:
    def __init__(self):
        self.rules = ONE_D_RULES
    
    def type_matches(self, kernel, tp):
        if tp == 'any':
            return True
        elif tp == 'base':
            return isinstance(kernel, fk.BaseKernel)
        else:
            raise RuntimeError('Unknown type: %s' % tp)
    
    def list_options(self, tp):
        if tp == 'any':
            raise RuntimeError("Can't expand the 'any' type")
        elif tp == 'base':
            return list(fk.base_kernel_families())
        else:
            raise RuntimeError('Unknown type: %s' % tp)
        
MULTI_D_RULES = [('A', ('+', 'A', 'B'), {'A': 'multi', 'B': 'mask'}),
                 ('A', ('*', 'A', 'B'), {'A': 'multi', 'B': 'mask'}),
                 ('A', 'B', {'A': 'base', 'B': 'base'}),
                 ]
    
class MultiDGrammar:
    def __init__(self, ndim, debug=False, base_kernels='SE'):
        self.rules = MULTI_D_RULES
        self.ndim = ndim
        self.debug = debug
        if not debug:
            self.base_kernels = base_kernels
        else:
            self.base_kernels = 'SE'
        
    def type_matches(self, kernel, tp):
        if tp == 'multi':
            if isinstance(kernel, fk.BaseKernel):
                return False
            elif isinstance(kernel, fk.MaskKernel):
                return True
            elif isinstance(kernel, fk.SumKernel):
                return all([self.type_matches(op, 'multi') for op in kernel.operands])
            elif isinstance(kernel, fk.ProductKernel):
                return all([self.type_matches(op, 'multi') for op in kernel.operands])
            else:
                raise RuntimeError('Invalid kernel: %s' % kernel.pretty_print())
        elif tp == '1d':
            if isinstance(kernel, fk.BaseKernel):
                return True
            elif isinstance(kernel, fk.MaskKernel):
                return False
            elif isinstance(kernel, fk.SumKernel):
                return all([self.type_matches(op, '1d') for op in kernel.operands])
            elif isinstance(kernel, fk.ProductKernel):
                return all([self.type_matches(op, '1d') for op in kernel.operands])
            else:
                raise RuntimeError('Invalid kernel: %s' % kernel.pretty_print())
        elif tp == 'base':
            return isinstance(kernel, fk.BaseKernel)
        elif tp == 'mask':
            return isinstance(kernel, fk.MaskKernel)
        else:
            raise RuntimeError('Unknown type: %s' % tp)
        
    def list_options(self, tp):
        if tp in ['1d', 'multi']:
            raise RuntimeError("Can't expand the '%s' type" % tp)
        elif tp == 'base':
            return [fam.default(self.ndim) for fam in fk.base_kernel_families(self.base_kernels)]
        elif tp == 'mask':
            return list(fk.base_kernels(self.ndim, self.base_kernels))
        else:
            raise RuntimeError('Unknown type: %s' % tp)
    
def replace_all(polish_expr, mapping):
    if type(polish_expr) == tuple:
        return tuple([replace_all(e, mapping) for e in polish_expr])
    elif type(polish_expr) == str:
        if polish_expr in mapping:
            return mapping[polish_expr].copy()
        else:
            return polish_expr
    else:
        assert isinstance(polish_expr, fk.Kernel)
        return polish_expr.copy()
    
def polish_to_kernel(polish_expr):
    if type(polish_expr) == tuple:
        if polish_expr[0] == '+':
            operands = [polish_to_kernel(e) for e in polish_expr[1:]]
            return fk.SumKernel(operands)
        elif polish_expr[0] == '*':
            operands = [polish_to_kernel(e) for e in polish_expr[1:]]
            return fk.ProductKernel(operands)
        else:
            raise RuntimeError('Unknown operator: %s' % polish_expr[0])
    else:
        assert isinstance(polish_expr, fk.Kernel)
        return polish_expr


def expand_single_tree(kernel, grammar):
    '''kernel should be a Kernel.'''
    assert isinstance(kernel, fk.Kernel)
    result = []
    for lhs, rhs, types in grammar.rules:
        if grammar.type_matches(kernel, types[lhs]):
            free_vars = types.keys()
            assert lhs in free_vars
            free_vars.remove(lhs)
            choices = itertools.product(*[grammar.list_options(types[v]) for v in free_vars])
            for c in choices:
                mapping = dict(zip(free_vars, c))
                mapping[lhs] = kernel
                full_polish = replace_all(rhs, mapping)
                result.append(polish_to_kernel(full_polish))
    return result

def expand(kernel, grammar):
    result = expand_single_tree(kernel, grammar)
    if isinstance(kernel, fk.BaseKernel):
        pass
    elif isinstance(kernel, fk.MaskKernel):
        result += [fk.MaskKernel(kernel.ndim, kernel.active_dimension, e)
                   for e in expand(kernel.base_kernel, grammar)]
    elif isinstance(kernel, fk.SumKernel):
        for i, op in enumerate(kernel.operands):
            for e in expand(op, grammar):
                new_ops = kernel.operands[:i] + [e] + kernel.operands[i+1:]
                new_ops = [op.copy() for op in new_ops]
                result.append(fk.SumKernel(new_ops))
    elif isinstance(kernel, fk.ProductKernel):
        for i, op in enumerate(kernel.operands):
            for e in expand(op, grammar):
                new_ops = kernel.operands[:i] + [e] + kernel.operands[i+1:]
                new_ops = [op.copy() for op in new_ops]
                result.append(fk.ProductKernel(new_ops))
    else:
        raise RuntimeError('Unknown kernel class:', kernel.__class__)
    return result

def canonical(kernel):
    '''Sorts a kernel tree into a canonical form.'''
    if isinstance(kernel, fk.BaseKernel):
        return kernel.copy()
    elif isinstance(kernel, fk.MaskKernel):
        return fk.MaskKernel(kernel.ndim, kernel.active_dimension, canonical(kernel.base_kernel))
    elif isinstance(kernel, fk.SumKernel):
        new_ops = []
        for op in kernel.operands:
            op_canon = canonical(op)
            if isinstance(op, fk.SumKernel):
                new_ops += op_canon.operands
            else:
                new_ops.append(op_canon)
        return fk.SumKernel(sorted(new_ops))
    elif isinstance(kernel, fk.ProductKernel):
        new_ops = []
        for op in kernel.operands:
            op_canon = canonical(op)
            if isinstance(op, fk.ProductKernel):
                new_ops += op_canon.operands
            else:
                new_ops.append(op_canon)
        return fk.ProductKernel(sorted(new_ops))
    else:
        raise RuntimeError('Unknown kernel class:', kernel.__class__)

def remove_duplicates(kernels):
    kernels = sorted(map(canonical, kernels))
    result = []
    curr = None
    for k in kernels:
        if curr is None or k != curr:
            result.append(k)
        curr = k
    return result
    
def expand_kernels(D, seed_kernels, verbose=False, debug=False, base_kernels='SE'):    
    '''Makes a list of all expansions of a set of kernels in D dimensions.'''
    g = MultiDGrammar(D, debug=debug, base_kernels=base_kernels)
    if verbose:
        print 'Seed kernels :'
        for k in seed_kernels:
            print k.pretty_print()
    kernels = []
    for k in seed_kernels:
        kernels = kernels + expand(k, g)
    kernels = remove_duplicates(kernels)
    if verbose:
        print 'Expanded kernels :'
        for k in kernels:
            print k.pretty_print()
    return (kernels)



            
