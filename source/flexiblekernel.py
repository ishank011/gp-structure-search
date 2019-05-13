'''
Created Nov 2012

@authors: James Robert Lloyd (jrl44@cam.ac.uk)
          David Duvenaud (dkd23@cam.ac.uk)
          Roger Grosse (rgrosse@mit.edu)
'''

import itertools
import numpy as np
try:
    import termcolor
    has_termcolor = True
except:
    has_termcolor = False

try:
    import config
    color_scheme = config.COLOR_SCHEME
except:
    color_scheme = 'dark'
    
from utils import psd_matrices
import utils.misc
import re

PAREN_COLORS = ['red', 'green', 'blue', 'cyan', 'magenta', 'yellow']
#### MAGIC NUMBER - CAUTION
CMP_TOLERANCE = np.log(1.01) # i.e. 1%

def shrink_below_tolerance(x):
    if np.abs(x) < CMP_TOLERANCE:
        return 0
    else:
        return x 

def paren_colors():
    if color_scheme == 'dark':
        return ['red', 'green', 'cyan', 'magenta', 'yellow']
    elif color_scheme == 'light':
        return ['blue', 'red', 'magenta', 'green', 'cyan']
    else:
        raise RuntimeError('Unknown color scheme: %s' % color_scheme)

def colored(text, depth):
    if has_termcolor:
        colors = paren_colors()
        color = colors[depth % len(colors)]
        return termcolor.colored(text, color, attrs=['bold'])
    else:
        return text

class KernelFamily:
    pass

class Kernel:
    def __add__(self, other):
        assert isinstance(other, Kernel)
        if isinstance(other, SumKernel):
            return SumKernel([self] + other.operands).copy()
        else:
            return SumKernel([self, other]).copy()
    
    def __mul__(self, other):
        assert isinstance(other, Kernel)
        if isinstance(other, ProductKernel):
            return ProductKernel([self] + other.operands).copy()
        else:
            return ProductKernel([self, other])

class BaseKernelFamily(KernelFamily):
    pass

class BaseKernel(Kernel):
    def effective_params(self):
        '''This is true of all base kernels, hence definition here'''  
        return len(self.param_vector()) - 1
        
    def default_params_replaced(self, sd=1, data_shape=None):
        '''Returns the parameter vector with any default values replaced with random Gaussian'''
        return [np.random.normal(scale=sd) if p == 0 else p for p in self.param_vector()]
        
    def out_of_bounds(self, constraints):
        '''Most kernels are allowed to have any parameter value'''
        return False

class SqExpKernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        lengthscale, output_variance, eff_dimensions = params
        return SqExpKernel(lengthscale=lengthscale, output_variance=output_variance, eff_dimensions=eff_dimensions)
    
    def num_params(self):
        return 3
    
    def pretty_print(self):
        return colored('SqExp', self.depth())
    
    def default(self, eff_dimensions):
        return SqExpKernel(0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'SE'
    
    @staticmethod    
    def description():
        return "Squared-exponential"

    @staticmethod    
    def params_description():
        return "lengthscale"    

class SqExpKernel(BaseKernel):
    def __init__(self, lengthscale, output_variance, eff_dimensions):
        self.lengthscale = lengthscale
        self.output_variance = output_variance
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return SqExpKernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covSEiso}'
    
    def english_name(self):
        return 'SqExp'
    
    def id_name(self):
        return 'SE'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.lengthscale, self.output_variance, self.eff_dimensions])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == 0:
            # Set lengthscale with input scale or neutrally
            if np.random.rand() < 0.5:
                result[0] = np.random.normal(loc=data_shape['input_scale'], scale=sd)
            else:
                result[0] = np.random.normal(loc=0, scale=sd)
        if result[1] == 0:
            # Set scale factor with output scale
            if np.random.rand() < 0.5:
                result[1] = np.random.normal(loc=data_shape['output_scale'], scale=sd)
            else:
                result[1] = np.random.normal(loc=0, scale=sd)
        return result

    def copy(self):
        return SqExpKernel(self.lengthscale, self.output_variance, self.eff_dimensions)
    
    def __repr__(self):
        return 'SqExpKernel(lengthscale=%f, output_variance=%f, eff_dimensions=%s)' % (self.lengthscale,
            self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('SE(ell=%1.1f, sf=%1.1f, dim=%s)' % (self.lengthscale, self.output_variance,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
    
    def latex_print(self):
        #return 'SE(\\ell=%1.1f, \\sigma=%1.1f)' % (self.lengthscale, self.output_variance)    
        #return 'SE(\\ell=%1.1f)' % self.lengthscale
        return 'SE'
        
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
    
    def depth(self):
        return 0
            
    def out_of_bounds(self, constraints):
        return self.lengthscale < constraints['min_lengthscale']


class SqExpPeriodicKernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        lengthscale, period, output_variance, eff_dimensions = params
        return SqExpPeriodicKernel(lengthscale, period, output_variance, eff_dimensions)
    
    def num_params(self):
        return 4
    
    def pretty_print(self):
        return colored('PE', self.depth())
    
    # FIXME - Caution - magic numbers!
    def default(self, eff_dimensions):
        return SqExpPeriodicKernel(0., -2.0, 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'Per'
    
    @staticmethod    
    def description():
        return "Periodic"

    @staticmethod    
    def params_description():
        return "lengthscale, period"  
    
class SqExpPeriodicKernel(BaseKernel):
    def __init__(self, lengthscale, period, output_variance, eff_dimensions):
        self.lengthscale = lengthscale
        self.period = period
        self.output_variance = output_variance
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return SqExpPeriodicKernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covPeriodic}'
    
    def english_name(self):
        return 'Periodic'
    
    def id_name(self):
        return 'Per'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.lengthscale, self.period, self.output_variance, self.eff_dimensions])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        '''Overwrites base method, using min period to prevent Nyquist errors'''
        result = self.param_vector()
        if result[0] == 0:
            # Min period represents a minimum sensible scale - use it for lengthscale as well
            # Scale with data_scale though
            if data_shape['min_period'] is None:
                if np.random.rand() < 0.5:
                    result[0] = np.random.normal(loc=data_shape['input_scale'], scale=sd)
                else:
                    result[0] = np.random.normal(loc=0, scale=sd)
            else:
                if np.random.rand() < 0.5:
                    result[0] = utils.misc.sample_truncated_normal(loc=data_shape['input_scale'], scale=sd, min_value=data_shape['min_period'])
                else:
                    result[0] = utils.misc.sample_truncated_normal(loc=0, scale=sd, min_value=data_shape['min_period'])
        if result[1] == -2:
            #### FIXME - Caution, magic numbers
            # Min period represents a minimum sensible scale
            # Scale with data_scale
            if data_shape['min_period'] is None:
                if np.random.rand() < 0.5:
                    result[1] = np.random.normal(loc=data_shape['input_scale']-2, scale=sd)
                else:
                    result[1] = np.random.normal(loc=-2, scale=sd)
            else:
                if np.random.rand() < 0.5:
                    result[1] = utils.misc.sample_truncated_normal(loc=data_shape['input_scale']-2, scale=sd, min_value=data_shape['min_period'])
                else:
                    result[1] = utils.misc.sample_truncated_normal(loc=-2, scale=sd, min_value=data_shape['min_period'])
        if result[2] == 0:
            # Set scale factor with output scale
            if np.random.rand() < 0.5:
                result[2] = np.random.normal(loc=data_shape['output_scale'], scale=sd)
            else:
                result[2] = np.random.normal(loc=0, scale=sd)
        return result

    def copy(self):
        return SqExpPeriodicKernel(self.lengthscale, self.period, self.output_variance, self.eff_dimensions)
    
    def __repr__(self):
        return 'SqExpPeriodicKernel(lengthscale=%f, period=%f, output_variance=%f, eff_dimensions=%s)' % \
            (self.lengthscale, self.period, self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('PE(ell=%1.1f, p=%1.1f, sf=%1.1f, dim=%s)' % (self.lengthscale, self.period, self.output_variance,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
        
    def latex_print(self):
        # return 'PE(\\ell=%1.1f, p=%1.1f, \\sigma=%1.1f)' % (self.lengthscale, self.period, self.output_variance)
        #return 'PE(p=%1.1f)' % self.period          
        return 'Per'
    
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.lengthscale - other.lengthscale, self.period - other.period, self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.lengthscale - other.lengthscale, self.period - other.period, self.output_variance - other.output_variance]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.period, self.output_variance), 
#                   (other.lengthscale, other.period, other.output_variance))
        
    def depth(self):
        return 0
            
    def out_of_bounds(self, constraints):
        return (self.period < constraints['min_period']) or (self.lengthscale < constraints['min_lengthscale'])
    

class RQKernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        lengthscale, output_variance, alpha, eff_dimensions = params
        return RQKernel(lengthscale, output_variance, alpha, eff_dimensions)
    
    def num_params(self):
        return 4
    
    def pretty_print(self):
        return colored('RQ', self.depth())
    
    def default(self, eff_dimensions):
        return RQKernel(0., 0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'RQ'
    
    @staticmethod    
    def description():
        return "Rational Quadratic"

    @staticmethod    
    def params_description():
        return "lengthscale, alpha"
        
    
class RQKernel(BaseKernel):
    def __init__(self, lengthscale, output_variance, alpha, eff_dimensions):
        self.lengthscale = lengthscale
        self.output_variance = output_variance
        self.alpha = alpha
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return RQKernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covRQiso}'
    
    def english_name(self):
        return 'RQ'
    
    def id_name(self):
        return 'RQ'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.lengthscale, self.output_variance, self.alpha, self.eff_dimensions, self.eff_dimensions])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == 0:
            # Set lengthscale with input scale
            if np.random.rand() < 0.5:
                result[0] = np.random.normal(loc=data_shape['input_scale'], scale=sd)
            else:
                result[0] = np.random.normal(loc=0, scale=sd)
        if result[1] == 0:
            # Set scale factor with output scale
            if np.random.rand() < 0.5:
                result[1] = np.random.normal(loc=data_shape['output_scale'], scale=sd)
            else:
                result[1] = np.random.normal(loc=0, scale=sd)
        if result[2] == 0:
            # Set alpha indepedently of data shape
            result[2] = np.random.normal(loc=0, scale=sd)
        return result

    def copy(self):
        return RQKernel(self.lengthscale, self.output_variance, self.alpha, self.eff_dimensions, self.eff_dimensions)
    
    def __repr__(self):
        return 'RQKernel(lengthscale=%f, output_variance=%f, alpha=%f, eff_dimensions=%s)' % \
            (self.lengthscale, self.output_variance, self.alpha, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('RQ(ell=%1.1f, sf=%1.1f, a=%1.1f, dim=%s)' % (self.lengthscale, self.output_variance, self.alpha,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
        
    def latex_print(self):
        #return 'RQ(\\ell=%1.1f, \\alpha=%1.1f, \\sigma=%1.1f)' % (self.lengthscale, self.alpha, self.output_variance)
        #return 'RQ(\\ell=%1.1f)' % self.lengthscale
        return 'RQ'           
    
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.lengthscale - other.lengthscale, self.output_variance - other.output_variance, self.alpha - other.alpha]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.lengthscale - other.lengthscale, self.output_variance - other.output_variance, self.alpha - other.alpha]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance, self.alpha), 
#                   (other.lengthscale, other.output_variance, other.alpha))
        
    def depth(self):
        return 0   
            
    def out_of_bounds(self, constraints):
        return (self.lengthscale < constraints['min_lengthscale']) or (self.alpha < constraints['min_alpha'])
    
class ConstKernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        #### Note - expects list input
        output_variance, eff_dimensions = params
        return ConstKernel(output_variance, eff_dimensions)
    
    def num_params(self):
        return 2
    
    def pretty_print(self):
        return colored('CS', self.depth())
    
    def default(self, eff_dimensions):
        return ConstKernel(0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'Const'
    
    @staticmethod    
    def description():
        return "Constant"

    @staticmethod    
    def params_description():
        return "Output variance"        
    
class ConstKernel(BaseKernel):
    def __init__(self, output_variance, eff_dimensions):
        self.output_variance = output_variance
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return ConstKernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covConst}'
    
    def english_name(self):
        return 'CS'
    
    def id_name(self):
        return 'Const'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.output_variance, self.eff_dimensions])

    def copy(self):
        return ConstKernel(self.output_variance, self.eff_dimensions)
        
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == 0:
            # Set scale factor with output scale
            result[0] = np.random.normal(loc=data_shape['output_scale'], scale=sd)
        return result
    
    def __repr__(self):
        return 'ConstKernel(output_variance=%f, eff_dimensions=%s)' % \
            (self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('CS(sf=%1.1f, dim=%s)' % (self.output_variance, ','.join([str(x) for x in self.eff_dimensions])),
                       self.depth())
        
    def latex_print(self):
        return 'CS'    
    
    def id_name(self):
        return 'Const'       
    
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.output_variance - other.output_variance]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance, self.alpha), 
#                   (other.lengthscale, other.output_variance, other.alpha))
        
    def depth(self):
        return 0    

class LinKernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        offset, lengthscale, location, eff_dimensions = params
        return LinKernel(offset=offset, lengthscale=lengthscale, location=location, eff_dimensions=eff_dimensions)
    
    def num_params(self):
        return 4
    
    def pretty_print(self):
        return colored('LN', self.depth())
    
    def default(self, eff_dimensions):
        return LinKernel(-2.0, 0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'Lin'

    @staticmethod    
    def description():
        return "Linear"

    @staticmethod    
    def params_description():
        return "bias"
    
class LinKernel(BaseKernel):
    # FIXME - Caution - magic numbers! This one means offset of essentially zero and scale of 1
    # FIXME - lengthscale is actually an inverse scale
    def __init__(self, offset, lengthscale, location, eff_dimensions):
        self.offset = offset
        self.lengthscale = lengthscale
        self.location = location
        self.eff_dimensions = eff_dimensions

    def family(self):
        return LinKernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covSum, {@covConst, @covLINscaleshift}}'
    
    def english_name(self):
        return 'LN'
    
    def id_name(self):
        return 'Lin'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.offset, self.lengthscale, self.location, self.eff_dimensions])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == -2:
            #### Caution - magic numbers - Offset assumed to be near zero since non zero means covered by constant kernel
            result[0] = np.random.normal(loc=-10, scale=sd)
        if result[1] == 0:
            # Lengthscale scales with ratio of y std and x std (gradient = delta y / delta x)
            if np.random.rand() < 0.5:
                result[1] = np.random.normal(loc=data_shape['output_scale'] - data_shape['input_scale'], scale=sd)
            else:
                result[1] = np.random.normal(loc=0, scale=sd)
        if result[2] == 0:
            # Location moves with input location, and variance scales in input variance
            result[2] = np.random.normal(loc=data_shape['input_location'], scale=sd*np.exp(data_shape['input_scale']))
        return result
        
    def effective_params(self):
        '''It's linear regression'''  
        return 2

    def copy(self):
        return LinKernel(offset=self.offset, lengthscale=self.lengthscale, location=self.location, eff_dimensions=self.eff_dimensions)
    
    def __repr__(self):
        return 'LinKernel(offset=%f, lengthscale=%f, location=%f, eff_dimensions=%s)' % \
            (self.offset, self.lengthscale, self.location, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('LN(off=%1.1f, ell=%1.1f, loc=%1.1f, dim=%s)' % (self.offset, self.lengthscale, self.location,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
        
    def latex_print(self):
        return 'Lin'           
    
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.offset - other.offset, self.lengthscale - other.lengthscale, self.location - other.location]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.lengthscale - other.lengthscale]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance, self.alpha), 
#                   (other.lengthscale, other.output_variance, other.alpha))
        
    def depth(self):
        return 0 

class QuadraticKernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        offset, output_variance, eff_dimensions = params
        return QuadraticKernel(offset, output_variance, eff_dimensions)
    
    def num_params(self):
        return 3
    
    def pretty_print(self):
        return colored('QD', self.depth())
    
    def default(self, eff_dimensions):
        return QuadraticKernel(0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'Quad'
    
    @staticmethod    
    def description():
        return "Quadratic"

    @staticmethod    
    def params_description():
        return "offset"     
    
class QuadraticKernel(BaseKernel):
    def __init__(self, offset, output_variance, eff_dimensions):
        #### FIXME - Should the offset defauly to something small? Or will we never use this kernel
        #### If using this kernel we should also add the default params replaced function
        self.offset = offset
        self.output_variance = output_variance
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return QuadraticKernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covPoly, 2}'
    
    def english_name(self):
        return 'QD'
    
    def id_name(self):
        return 'Quad'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.offset, self.output_variance, self.eff_dimensions])

    def copy(self):
        return QuadraticKernel(self.offset, self.output_variance, self.eff_dimensions)
    
    def __repr__(self):
        return 'QuadraticKernel(offset=%f, output_variance=%f, eff_dimensions=%s)' % \
            (self.offset, self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('QD(off=%1.1f, sf=%1.1f, dim=%s)' % (self.offset, self.output_variance,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
        
    def latex_print(self):
        return 'QD'           
    
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.offset - other.offset, self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.offset - other.offset, self.output_variance - other.output_variance]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance, self.alpha), 
#                   (other.lengthscale, other.output_variance, other.alpha))
        
    def depth(self):
        return 0   

class CubicKernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        offset, output_variance, eff_dimensions = params
        return CubicKernel(offset, output_variance, eff_dimensions)
    
    def num_params(self):
        return 3
    
    def pretty_print(self):
        return colored('CB', self.depth())
    
    def default(self, eff_dimensions):
        return CubicKernel(0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'Cubic'
    
    @staticmethod    
    def description():
        return "Cubic"

    @staticmethod    
    def params_description():
        return "offset"     
    
class CubicKernel(BaseKernel):
    def __init__(self, offset, output_variance, eff_dimensions):
        #### FIXME - Should the offset defauly to something small? Or will we never use this kernel
        #### If using this kernel we should also add the default params replaced function
        self.offset = offset
        self.output_variance = output_variance
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return CubicKernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covPoly, 3}'
    
    def english_name(self):
        return 'CB'
    
    def id_name(self):
        return 'Cubic'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.offset, self.output_variance, self.eff_dimensions])

    def copy(self):
        return CubicKernel(self.offset, self.output_variance, self.eff_dimensions)
    
    def __repr__(self):
        return 'CubicKernel(offset=%f, output_variance=%f, eff_dimensions=%s)' % \
            (self.offset, self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('CB(off=%1.1f, sf=%1.1f, dim=%s)' % (self.offset, self.output_variance,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
        
    def latex_print(self):
        return 'CB'           
    
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.offset - other.offset, self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.offset - other.offset, self.output_variance - other.output_variance]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance, self.alpha), 
#                   (other.lengthscale, other.output_variance, other.alpha))
        
    def depth(self):
        return 0   

class PP0KernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        lengthscale, output_variance, eff_dimensions = params
        return PP0Kernel(lengthscale, output_variance, eff_dimensions)
    
    def num_params(self):
        return 3
    
    def pretty_print(self):
        return colored('P0', self.depth())
    
    def default(self, eff_dimensions):
        return PP0Kernel(0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'PP0'

    @staticmethod    
    def description():
        return "Piecewise Polynomial 0"

    @staticmethod    
    def params_description():
        return "lengthscale"   
    

class PP0Kernel(BaseKernel):
    def __init__(self, lengthscale, output_variance, eff_dimensions):
        self.output_variance = output_variance
        self.lengthscale = lengthscale
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return PP0KernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covPPiso, 0}'
    
    def english_name(self):
        return 'P0'
    
    def id_name(self):
        return 'PP0'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.lengthscale, self.output_variance, self.eff_dimensions])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == 0:
            # Set lengthscale with input scale
            if np.random.rand() < 0.5:
                result[0] = np.random.normal(loc=data_shape['input_scale'], scale=sd)
            else:
                result[0] = np.random.normal(loc=0, scale=sd)
        if result[1] == 0:
            # Set scale factor with output scale
            if np.random.rand() < 0.5:
                result[1] = np.random.normal(loc=data_shape['output_scale'], scale=sd)
            else:
                result[1] = np.random.normal(loc=0, scale=sd)
        return result

    def copy(self):
        return PP0Kernel(self.lengthscale, self.output_variance, self.eff_dimensions)
    
    def __repr__(self):
        return 'PP0Kernel(lengthscale=%f, output_variance=%f, eff_dimensions=%s)' % (self.lengthscale,
            self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('P0(ell=%1.1f, sf=%1.1f, dim=%s)' % (self.lengthscale, self.output_variance,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
    
    def latex_print(self):
        #return 'SE(\\ell=%1.1f, \\sigma=%1.1f)' % (self.lengthscale, self.output_variance)    
        #return 'SE(\\ell=%1.1f)' % self.lengthscale
        return 'P0'
        
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance), (other.lengthscale, other.output_variance))
    
    def depth(self):
        return 0 
            
    def out_of_bounds(self, constraints):
        return self.lengthscale < constraints['min_lengthscale']
      

class PP1KernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        lengthscale, output_variance, eff_dimensions = params
        return PP1Kernel(lengthscale, output_variance, eff_dimensions)
    
    def num_params(self):
        return 3
    
    def pretty_print(self):
        return colored('P1', self.depth())
    
    def default(self, eff_dimensions):
        return PP1Kernel(0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'PP1'
    
    @staticmethod    
    def description():
        return "Piecewise Polynomial 1"

    @staticmethod    
    def params_description():
        return "lengthscale"      

class PP1Kernel(BaseKernel):
    def __init__(self, lengthscale, output_variance, eff_dimensions):
        self.output_variance = output_variance
        self.lengthscale = lengthscale
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return PP1KernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covPPiso, 1}'
    
    def english_name(self):
        return 'P1'
    
    def id_name(self):
        return 'PP1'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.lengthscale, self.output_variance, self.eff_dimensions])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == 0:
            # Set lengthscale with input scale
            if np.random.rand() < 0.5:
                result[0] = np.random.normal(loc=data_shape['input_scale'], scale=sd)
            else:
                result[0] = np.random.normal(loc=0, scale=sd)
        if result[1] == 0:
            # Set scale factor with output scale
            if np.random.rand() < 0.5:
                result[1] = np.random.normal(loc=data_shape['output_scale'], scale=sd)
            else:
                result[1] = np.random.normal(loc=0, scale=sd)
        return result

    def copy(self):
        return PP1Kernel(self.lengthscale, self.output_variance, self.eff_dimensions)
    
    def __repr__(self):
        return 'PP1Kernel(lengthscale=%f, output_variance=%f, eff_dimensions=%s)' % (self.lengthscale,
            self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('P1(ell=%1.1f, sf=%1.1f, dim=%s)' % (self.lengthscale, self.output_variance,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
    
    def latex_print(self):
        #return 'SE(\\ell=%1.1f, \\sigma=%1.1f)' % (self.lengthscale, self.output_variance)    
        #return 'SE(\\ell=%1.1f)' % self.lengthscale
        return 'P1'
        
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance), (other.lengthscale, other.output_variance))
    
    def depth(self):
        return 0 
            
    def out_of_bounds(self, constraints):
        return self.lengthscale < constraints['min_lengthscale']
        

class PP2KernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        lengthscale, output_variance, eff_dimensions = params
        return PP2Kernel(lengthscale, output_variance, eff_dimensions)
    
    def num_params(self):
        return 3
    
    def pretty_print(self):
        return colored('P2', self.depth())
    
    def default(self, eff_dimensions):
        return PP2Kernel(0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'PP2'
    
    @staticmethod    
    def description():
        return "Piecewise Polynomial 2"

    @staticmethod    
    def params_description():
        return "lengthscale"      

class PP2Kernel(BaseKernel):
    def __init__(self, lengthscale, output_variance, eff_dimensions):
        self.output_variance = output_variance
        self.lengthscale = lengthscale
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return PP2KernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covPPiso, 2}'
    
    def english_name(self):
        return 'P2'
    
    def id_name(self):
        return 'PP2'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.lengthscale, self.output_variance, self.eff_dimensions])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == 0:
            # Set lengthscale with input scale
            if np.random.rand() < 0.5:
                result[0] = np.random.normal(loc=data_shape['input_scale'], scale=sd)
            else:
                result[0] = np.random.normal(loc=0, scale=sd)
        if result[1] == 0:
            # Set scale factor with output scale
            if np.random.rand() < 0.5:
                result[1] = np.random.normal(loc=data_shape['output_scale'], scale=sd)
            else:
                result[1] = np.random.normal(loc=0, scale=sd)
        return result

    def copy(self):
        return PP2Kernel(self.lengthscale, self.output_variance, self.eff_dimensions)
    
    def __repr__(self):
        return 'PP2Kernel(lengthscale=%f, output_variance=%f, eff_dimensions=%s)' % (self.lengthscale,
            self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('P2(ell=%1.1f, sf=%1.1f, dim=%s)' % (self.lengthscale, self.output_variance,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
    
    def latex_print(self):
        #return 'SE(\\ell=%1.1f, \\sigma=%1.1f)' % (self.lengthscale, self.output_variance)    
        #return 'SE(\\ell=%1.1f)' % self.lengthscale
        return 'P2'
        
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance), (other.lengthscale, other.output_variance))
    
    def depth(self):
        return 0
            
    def out_of_bounds(self, constraints):
        return self.lengthscale < constraints['min_lengthscale']


class PP3KernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        lengthscale, output_variance, eff_dimensions = params
        return PP3Kernel(lengthscale, output_variance, eff_dimensions)
    
    def num_params(self):
        return 3
    
    def pretty_print(self):
        return colored('P3', self.depth())
    
    def default(self, eff_dimensions):
        return PP3Kernel(0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'PP3'
    
    @staticmethod    
    def description():
        return "Piecewise Polynomial 3"

    @staticmethod    
    def params_description():
        return "lengthscale"       

class PP3Kernel(BaseKernel):
    def __init__(self, lengthscale, output_variance, eff_dimensions):
        self.output_variance = output_variance
        self.lengthscale = lengthscale
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return PP3KernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covPPiso, 3}'
    
    def english_name(self):
        return 'P3'
    
    def id_name(self):
        return 'PP3'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.lengthscale, self.output_variance, self.eff_dimensions])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == 0:
            # Set lengthscale with input scale
            if np.random.rand() < 0.5:
                result[0] = np.random.normal(loc=data_shape['input_scale'], scale=sd)
            else:
                result[0] = np.random.normal(loc=0, scale=sd)
        if result[1] == 0:
            # Set scale factor with output scale
            if np.random.rand() < 0.5:
                result[1] = np.random.normal(loc=data_shape['output_scale'], scale=sd)
            else:
                result[1] = np.random.normal(loc=0, scale=sd)
        return result

    def copy(self):
        return PP3Kernel(self.lengthscale, self.output_variance, self.eff_dimensions)
    
    def __repr__(self):
        return 'PP3Kernel(lengthscale=%f, output_variance=%f, eff_dimensions=%s)' % (self.lengthscale,
            self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('P3(ell=%1.1f, sf=%1.1f, dim=%s)' % (self.lengthscale, self.output_variance,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
    
    def latex_print(self):
        #return 'SE(\\ell=%1.1f, \\sigma=%1.1f)' % (self.lengthscale, self.output_variance)    
        #return 'SE(\\ell=%1.1f)' % self.lengthscale
        return 'P3'
        
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance), (other.lengthscale, other.output_variance))
    
    def depth(self):
        return 0 
            
    def out_of_bounds(self, constraints):
        return self.lengthscale < constraints['min_lengthscale']

class MaternKernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        lengthscale, output_variance, eff_dimensions = params
        return MaternKernel(lengthscale, output_variance, eff_dimensions)
    
    def num_params(self):
        return 3
    
    def pretty_print(self):
        return colored('MT', self.depth())
    
    def default(self, eff_dimensions):
        return MaternKernel(0., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'MT'
    
    @staticmethod    
    def description():
        return "Mat\\'{e}rn"

    @staticmethod    
    def params_description():
        return "lengthscale"    

class MaternKernel(BaseKernel):
    def __init__(self, lengthscale, output_variance, eff_dimensions):
        self.lengthscale = lengthscale
        self.output_variance = output_variance
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return MaternKernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covMaterniso, 1}' # nu = 0.5
    
    def english_name(self):
        return 'MT'
    
    def id_name(self):
        return 'MT'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.lengthscale, self.output_variance, self.eff_dimensions])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == 0:
            # Set lengthscale with input scale
            if np.random.rand() < 0.5:
                result[0] = np.random.normal(loc=data_shape['input_scale'], scale=sd)
            else:
                result[0] = np.random.normal(loc=0, scale=sd)
        if result[1] == 0:
            # Set scale factor with output scale
            if np.random.rand() < 0.5:
                result[1] = np.random.normal(loc=data_shape['output_scale'], scale=sd)
            else:
                result[1] = np.random.normal(loc=0, scale=sd)
        return result

    def copy(self):
        return MaternKernel(self.lengthscale, self.output_variance, self.eff_dimensions)
    
    def __repr__(self):
        return 'MaternKernel(lengthscale=%f, output_variance=%f, eff_dimensions=%s)' % (self.lengthscale,
            self.output_variance, '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('MT(ell=%1.1f, sf=%1.1f, dim=%s)' % (self.lengthscale, self.output_variance,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
    
    def latex_print(self):
        #return 'SE(\\ell=%1.1f, \\sigma=%1.1f)' % (self.lengthscale, self.output_variance)    
        #return 'SE(\\ell=%1.1f)' % self.lengthscale
        return 'MT'
        
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
#        max_diff = max(np.abs([self.lengthscale - other.lengthscale, self.output_variance - other.output_variance]))
#        return max_diff > CMP_TOLERANCE
#        return cmp((self.lengthscale, self.output_variance), (other.lengthscale, other.output_variance))
    
    def depth(self):
        return 0 
            
    def out_of_bounds(self, constraints):
        return self.lengthscale < constraints['min_lengthscale']
    
class ChangeKernelFamily(BaseKernelFamily):
    def from_param_vector(self, params):
        steepness, location, eff_dimensions = params
        return ChangeKernel(steepness, location, eff_dimensions)
    
    def num_params(self):
        return 3
    
    def pretty_print(self):
        return colored('CH', self.depth())
    
    def default(self, eff_dimensions):
        # A steepness of exactly zero will result in no gradient.
        # We might consider reparameterizing at some point.
        # The parameters aren't in log space.
        #### TODO - Put steepness parameter in log space for consistency since this will scale like a lengthscale
        return ChangeKernel(1., 0., range(eff_dimensions))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return 0
    
    def depth(self):
        return 0
    
    def id_name(self):
        return 'Change'
    
    @staticmethod    
    def description():
        return "Changepoint"

    @staticmethod    
    def params_description():
        return "steepness, location"    

class ChangeKernel(BaseKernel):
    def __init__(self, steepness, location, eff_dimensions):
        self.steepness = steepness
        self.location = location
        self.eff_dimensions = eff_dimensions
        
    def family(self):
        return ChangeKernelFamily()
        
    def gpml_kernel_expression(self):
        return '{@covChange}'
    
    def english_name(self):
        return 'CH'
    
    def id_name(self):
        return 'Change'
    
    def param_vector(self):
        # order of args matches GPML
        return np.array([self.steepness, self.location, self.eff_dimensions])
    
    #### TODO - Uncomment me when this kernel is implemented
    #### N.B. This assumes the steepness parameter is on a log scale and scales like a lengthscale    
    def default_params_replaced(self, sd=1, data_shape=None):
        result = self.param_vector()
        if result[0] == 0: #### TODO - Make sure this default matches that in self.default() - should do when on log scale
            # Set steepness with input scale
            result[0] = np.random.normal(loc=data_shape['input_scale'], scale=sd)
        if result[1] == 0:
            # Location moves with input location, and variance scales in input variance
            result[1] = np.random.normal(loc=data_shape['input_location'], scale=sd*np.exp(data_shape['input_scale']))
        return result

    def copy(self):
        return ChangeKernel(self.steepness, self.location, self.eff_dimensions)
    
    def __repr__(self):
        return 'ChangeKernel(steepness=%f, location=%f, eff_dimensions=%s)' % (self.steepness, self.location,
            '['+','.join([str(x) for x in self.eff_dimensions])+']')
    
    def pretty_print(self):
        return colored('CH(steep=%1.1f, loc=%1.1f, dim=%s)' % (self.steepness, self.location,
            ','.join([str(x) for x in self.eff_dimensions])), self.depth())
    
    def latex_print(self):
        return 'Change'
        
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        differences = [self.steepness - other.steepness, self.location - other.location]
        differences = map(shrink_below_tolerance, differences)
        return cmp(differences, [0] * len(differences))
    
    def depth(self):
        return 0 
    
        
class MaskKernelFamily(KernelFamily):
    def __init__(self, ndim, active_dimension, base_kernel_family):
        assert 0 <= active_dimension < ndim
        self.ndim = ndim
        self.active_dimension = active_dimension    # first dimension is 0
        self.base_kernel_family = base_kernel_family
        
    def from_param_vector(self, params):
        return MaskKernel(self.ndim, self.active_dimension, self.base_kernel_family.from_param_vector(params))
    
    def num_params(self):
        return self.base_kernel_family.num_params()
    
    def pretty_print(self):
        #return colored('Mask(%d, ' % self.active_dimension, self.depth()) + \
        return colored('M(%d, ' % self.active_dimension, self.depth()) + \
            self.base_kernel_family.pretty_print() + \
            colored(')', self.depth())
    
    def default(self):
        return MaskKernel(self.ndim, self.active_dimension, self.base_kernel_family.default(self.ndim))
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return cmp((self.ndim, self.active_dimension, self.base_kernel_family),
                   (other.ndim, other.active_dimension, other.base_kernel_family))
        
    def depth(self):
        return self.base_kernel_family.depth() + 1
    
    
class MaskKernel(Kernel):
    def __init__(self, ndim, active_dimension, base_kernel):
        assert 0 <= active_dimension < ndim
        self.ndim = ndim
        self.active_dimension = active_dimension    # first dimension is 0
        self.base_kernel = base_kernel
        
    def copy(self):
        return MaskKernel(self.ndim, self.active_dimension, self.base_kernel.copy())
        
    def family(self):
        return MaskKernelFamily(self.ndim, self.active_dimension, self.base_kernel.family())
        
    def gpml_kernel_expression(self):
        dim_vec = np.zeros(self.ndim, dtype=int)
        dim_vec[self.active_dimension] = 1
        dim_vec_str = '[' + ' '.join(map(str, dim_vec)) + ']'
        return '{@covMask, {%s, %s}}' % (dim_vec_str, self.base_kernel.gpml_kernel_expression())
    
    def pretty_print(self):
        return colored('M(%d, ' % self.active_dimension, self.depth()) + \
            self.base_kernel.pretty_print() + \
            colored(')', self.depth())
            
    def latex_print(self):
        #return 'M_%d \\left(' % self.active_dimension + self.base_kernel.latex_print() + '\\right)'                 
        return self.base_kernel.latex_print() + '_{%d}' % self.active_dimension
            
    def __repr__(self):
        return 'MaskKernel(ndim=%d, active_dimension=%d, base_kernel=%s)' % \
            (self.ndim, self.active_dimension, self.base_kernel.__repr__())            
    
    def param_vector(self):
        return self.base_kernel.param_vector()
        
    def effective_params(self):
        return self.base_kernel.effective_params()
        
    def default_params_replaced(self, sd=1, data_shape=None):
        # Replaces multi-d parameters with appropriate dimensions selected
        # If parameters are already 1-d then it does nothing
        if isinstance(data_shape['input_location'], (list, tuple, np.ndarray)):
            data_shape['input_location'] = data_shape['input_location'][self.active_dimension]
        if isinstance(data_shape['input_scale'], (list, tuple, np.ndarray)):
            data_shape['input_scale'] = data_shape['input_scale'][self.active_dimension]
        if isinstance(data_shape['min_period'], (list, tuple, np.ndarray)):
            data_shape['min_period'] = data_shape['min_period'][self.active_dimension]
        return self.base_kernel.default_params_replaced(sd=sd, data_shape=data_shape)
    
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return cmp((self.ndim, self.active_dimension, self.base_kernel),
                   (other.ndim, other.active_dimension, other.base_kernel))
        
    def depth(self):
        return self.base_kernel.depth() + 1
            
    def out_of_bounds(self, constraints):
        # Extract relevant constraints
        if isinstance(constraints['min_period'], (list, tuple, np.ndarray)):
            # Pick out relevant minimum period
            constraints['min_period'] = constraints['min_period'][self.active_dimension]
        else:
            # min_period either one dimensional or None - do nothing
            pass
        return self.base_kernel.out_of_bounds(constraints)
    

class SumKernelFamily(KernelFamily):
    def __init__(self, operands):
        self.operands = operands
        
    def from_param_vector(self, params):
        start = 0
        ops = []
        for e in self.operands:
            end = start + e.num_params()
            ops.append(e.from_param_vector(params[start:end]))
            start = end
        return SumKernel(ops)
    
    def num_params(self):
        return sum([e.num_params() for e in self.operands])
    
    def pretty_print(self):
        op = colored(' + ', self.depth())
        return colored('( ', self.depth()) + \
            op.join([e.pretty_print() for e in self.operands]) + \
            colored(' ) ', self.depth())
    
    def default(self):
        return SumKernel([op.default() for op in self.operands])
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return cmp(self.operands, other.operands)
    
    def depth(self):
        return max([op.depth() for op in self.operands]) + 1

class SumKernel(Kernel):
    def __init__(self, operands):
        self.operands = operands
        
    def family(self):
        return SumKernelFamily([e.family() for e in self.operands])
        
    def pretty_print(self):
        #### Should this call the family method?
        op = colored(' + ', self.depth())
        return colored('( ', self.depth()) + \
            op.join([e.pretty_print() for e in self.operands]) + \
            colored(' ) ', self.depth())
            
    def latex_print(self):
        return '\\left( ' + ' + '.join([e.latex_print() for e in self.operands]) + ' \\right)'            
            
    def __repr__(self):
        return 'SumKernel(%s)' % \
            ('[ ' + ', '.join([o.__repr__() for o in self.operands]) + ' ]')                
    
    def gpml_kernel_expression(self):
        return '{@covSum, {%s}}' % ', '.join(e.gpml_kernel_expression() for e in self.operands)
    
    def copy(self):
        return SumKernel([e.copy() for e in self.operands])

    def param_vector(self):
        return np.concatenate([e.param_vector() for e in self.operands])
        
    def effective_params(self):
        return sum([o.effective_params() for o in self.operands])
        
    def default_params_replaced(self, sd=1, data_shape=None):
        '''Returns the parameter vector with any default values replaced with random Gaussian'''
        return np.concatenate([o.default_params_replaced(sd=sd, data_shape=data_shape) for o in self.operands])
    
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return cmp(self.operands, other.operands)
    
    def depth(self):
        return max([op.depth() for op in self.operands]) + 1
    
    def __add__(self, other):
        assert isinstance(other, Kernel)
        if isinstance(other, SumKernel):
            return SumKernel(self.operands + other.operands).copy()
        else:
            return SumKernel(self.operands + [other]).copy()
            
    def out_of_bounds(self, constraints):
        return any([o.out_of_bounds(constraints) for o in self.operands]) 
    
class ProductKernelFamily(KernelFamily):
    def __init__(self, operands):
        self.operands = operands
        
    def from_param_vector(self, params):
        start = 0
        ops = []
        for o in self.operands:
            end = start + o.num_params()
            ops.append(o.from_param_vector(params[start:end]))
            start = end
        return ProductKernel(ops)
    
    def num_params(self):
        return sum([e.num_params() for e in self.operands])
    
    def pretty_print(self):
        op = colored(' x ', self.depth())
        return colored('( ', self.depth()) + \
            op.join([e.pretty_print() for e in self.operands]) + \
            colored(' ) ', self.depth())
    
    def default(self):
        return ProductKernel([op.default() for op in self.operands])
    
    def __cmp__(self, other):
        assert isinstance(other, KernelFamily)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return cmp(self.operands, other.operands)
    
    def depth(self):
        return max([op.depth() for op in self.operands]) + 1
    
class ProductKernel(Kernel):
    def __init__(self, operands):
        self.operands = operands
        
    def family(self):
        return ProductKernelFamily([e.family() for e in self.operands])
        
    def pretty_print(self):
        #### Should this call the family method?
        op = colored(' x ', self.depth())
        return colored('( ', self.depth()) + \
            op.join([e.pretty_print() for e in self.operands]) + \
            colored(' ) ', self.depth())

    def latex_print(self):
        #return '\\left( ' + ' \\times '.join([e.latex_print() for e in self.operands]) + ' \\right)'
        # Don't need brackets for product, order of operations is unambiguous, I think.
        return ' \\times '.join([e.latex_print() for e in self.operands])
            
    def __repr__(self):
        return 'ProductKernel(%s)' % \
            ('[ ' + ', '.join([o.__repr__() for o in self.operands]) + ' ]')              
    
    def gpml_kernel_expression(self):
        return '{@covProd, {%s}}' % ', '.join(e.gpml_kernel_expression() for e in self.operands)
    
    def copy(self):
        return ProductKernel([e.copy() for e in self.operands])

    def param_vector(self):
        return np.concatenate([e.param_vector() for e in self.operands])
        
    def effective_params(self):
        '''The scale of a product of kernels is over parametrised'''
        return sum([o.effective_params() for o in self.operands]) - (len(self.operands) - 1)
        
    def default_params_replaced(self, sd=1, data_shape=None):
        '''Returns the parameter vector with any default values replaced with random Gaussian'''
        return np.concatenate([o.default_params_replaced(sd=sd, data_shape=data_shape) for o in self.operands])
    
    def __cmp__(self, other):
        assert isinstance(other, Kernel)
        if cmp(self.__class__, other.__class__):
            return cmp(self.__class__, other.__class__)
        return cmp(self.operands, other.operands)
    
    def depth(self):
        return max([op.depth() for op in self.operands]) + 1
    
    def __mul__(self, other):
        assert isinstance(other, Kernel)
        if isinstance(other, ProductKernel):
            return ProductKernel(self.operands + other.operands).copy()
        else:
            return ProductKernel(self.operands + [other]).copy()
            
    def out_of_bounds(self, constraints):
        return any([o.out_of_bounds(constraints) for o in self.operands]) 


#### FIXME - Sort out the naming of the two functions below            
def base_kernels(ndim=1, base_kernel_names='SE'):
    '''
    Generator of all base kernels for a certain dimensionality of data
    '''
    for dim in range(ndim):
        for fam in base_kernel_families(base_kernel_names):
            yield MaskKernel(ndim, dim, fam.default(ndim))
    #if ndim == 1:
    #    for k in base_kernel_families(ndim):
    #        yield MaskKernel(ndim, 0, k)
    #        # Todo: fix 1D kernels to work without MaskKernels.
    #else:
    #    for dim in range(ndim):
    #        for k in multi_d_kernel_families():
    #            yield MaskKernel(ndim, dim, k)
 
def base_kernel_families(base_kernel_names):
    '''
    Generator of all base kernel families.
    '''
    for family in [SqExpKernelFamily(), \
                   SqExpPeriodicKernelFamily(), \
                   RQKernelFamily(), \
                   ConstKernelFamily(), \
                   LinKernelFamily(), \
                   ChangeKernelFamily(), \
                   QuadraticKernelFamily(), \
                   CubicKernelFamily(), \
                   PP0KernelFamily(), \
                   PP1KernelFamily(), \
                   PP2KernelFamily(), \
                   PP3KernelFamily(), \
                   MaternKernelFamily()]:
        if family.id_name() in base_kernel_names.split(','):
            yield family
    #if ndim == 1:
    #    yield SqExpKernelFamily().default()
    #    yield SqExpPeriodicKernelFamily().default()
    #    yield RQKernelFamily().default()
    #    yield LinKernelFamily().default()
    #    #yield ChangeKernelFamily().default()
    #else:
    #    yield SqExpKernelFamily().default()
    #    yield SqExpPeriodicKernelFamily().default()
    #    yield RQKernelFamily().default()
    #    yield LinKernelFamily().default()
    #yield QuadraticKernelFamily().default()
    #yield CubicKernelFamily().default()
    #yield PP0KernelFamily().default()
    #yield PP1KernelFamily().default()
    #yield PP2KernelFamily().default()
    #yield PP3KernelFamily().default()
    #yield MaternKernelFamily().default()       

#def multi_d_kernel_families():
#    '''
#    Generator of all base kernel families for multidimensional problems.
#    '''
#    yield SqExpKernelFamily().default()
#    yield SqExpPeriodicKernelFamily().default()
#    yield RQKernelFamily().default()
#    yield LinKernelFamily().default()  
   
   
#### FIXME - Do the two functions below get called ever?        
def test_kernels(ndim=1):
    '''
    Generator of a subset of base kernels for testing
    '''
    for dim in range(ndim):
        for k in test_kernel_families():
            yield MaskKernel(ndim, dim, k) 
         
def test_kernel_families():
    '''
    Generator of all base kernel families
    '''
    yield SqExpKernelFamily().default()
    #yield SqExpPeriodicKernelFamily().default() 
    #yield RQKernelFamily().default()       

def Carls_Mauna_kernel():
    '''
    This kernel described in pages 120-122 of "Gaussian Processes for Machine Learning.
    This model was learnt on the mauna dataset up to 2003.
    
    The reported nll in the book for this dataset is 108.5
    '''
    theta_1 = np.log(66.)  # ppm, sf of SE1 = magnitude of long term trend
    theta_2 = np.log(67.)  # years, ell of SE1 = lengthscale of long term trend
    theta_6 = np.log(0.66)  # ppm, sf of RQ = magnitude of med term trend
    theta_7 = np.log(1.2)  # years, ell of RQ = lengthscale of med term trend
    theta_8 = np.log(0.78) # alpha of RQ
    theta_3 = np.log(2.4) # ppm, sf of periodic * SE
    theta_4 = np.log(90.) # years, lengthscale of SE of periodic*SE
    theta_5 = np.log(1.3) # smoothness of periodic
    theta_9 = np.log(0.18) # ppm, amplitude of SE_noise
    theta_10 = np.log(1.6/12.0) # years (originally months), lengthscale of SE_noise
    theta_11 = np.log(0.19) # ppm, amplitude of independent noise
    
    kernel = SqExpKernel(output_variance=theta_1, lengthscale=theta_2) \
           + SqExpKernel(output_variance=theta_3, lengthscale=theta_4) * SqExpPeriodicKernel(output_variance=0, period=0, lengthscale=theta_5) \
           + RQKernel(lengthscale=theta_7, output_variance=theta_6, alpha=theta_8) \
           + SqExpKernel(output_variance=theta_9, lengthscale=theta_10)
    
    return kernel


def strip_masks(k):
    """Recursively strips masks out of a kernel, for when we used a multi-d grammar on a 1d problem."""    
    if isinstance(k, MaskKernel):
        return strip_masks(k.base_kernel)
    elif isinstance(k, SumKernel):
        return SumKernel([strip_masks(op) for op in k.operands])
    elif isinstance(k, ProductKernel):
        return ProductKernel([strip_masks(op) for op in k.operands])
    else:
        return k  

def break_kernel_into_summands(k):
    '''Takes a kernel, expands it into a polynomial, and breaks terms up into a list.
    
    Mutually Recursive with distribute_products().
    Always returns a list.
    '''    
    # First, recursively distribute all products within the kernel.
    k_dist = distribute_products(k)
    
    if isinstance(k_dist, SumKernel):
        # Break the summands into a list of kernels.
        return list(k_dist.operands)
    else:
        return [k_dist]

def distribute_products(k):
    """Distributes products to get a polynomial.
    
    Mutually recursive with break_kernel_into_summands().
    Always returns a sumkernel.
    """

    if isinstance(k, ProductKernel):
        # Recursively distribute each of the terms to be multiplied.
        distributed_ops = [break_kernel_into_summands(op) for op in k.operands]
        
        # Now produce a sum of all combinations of terms in the products. Itertools is awesome.
        new_prod_ks = [ProductKernel( prod ) for prod in itertools.product(*distributed_ops)]
        return SumKernel(new_prod_ks)
    
    elif isinstance(k, SumKernel):
        # Recursively distribute each the operands to be summed, then combine them back into a new SumKernel.
        return SumKernel([subop for op in k.operands for subop in break_kernel_into_summands(op)])
    else:
        # Base case: A kernel that's just, like, a kernel, man.
        return k
        
from numpy import nan

def repr_string_to_kernel(string):
    """This is defined in this module so that all the kernel class names
    don't have to have the module name in front of them."""
    return eval(string)

class ScoredKernel:
    '''
    Wrapper around a kernel with various scores and noise parameter
    '''
    def __init__(self, k_opt, nll, laplace_nle, bic_nle, noise):
        self.k_opt = k_opt
        self.nll = nll
        self.laplace_nle = laplace_nle
        self.bic_nle = bic_nle
        self.noise = noise
        
    def score(self, criterion='bic'):
        #### FIXME - Change default to laplace when it is definitely bug free
        return {'bic': self.bic_nle,
                'nll': self.nll,
                'laplace': self.laplace_nle
                }[criterion]
                
    @staticmethod
    def from_printed_outputs(nll, laplace, BIC, noise=None, kernel=None):
        return ScoredKernel(kernel, nll, laplace, BIC, noise)
    
    def __repr__(self):
        return 'ScoredKernel(k_opt=%s, nll=%f, laplace_nle=%f, bic_nle=%f, noise=%s)' % \
            (self.k_opt, self.nll, self.laplace_nle, self.bic_nle, self.noise)

    def pretty_print(self):
        return self.k_opt.pretty_print()

    def latex_print(self):
        return self.k_opt.latex_print()

    @staticmethod   
    def from_matlab_output(output, kernel_family, ndata):
        '''Computes Laplace marginal lik approx and BIC - returns scored Kernel'''
        #laplace_nle, problems = psd_matrices.laplace_approx_stable(output.nll, output.kernel_hypers, output.hessian)
        #laplace_nle = psd_matrices.laplace_approx_no_prior(output.nll, np.concatenate((output.kernel_hypers, output.noise_hyp)), output.hessian)
        laplace_nle = np.nan
        k_opt = kernel_family.from_param_vector(output.kernel_hypers)
        BIC = 2 * output.nll + k_opt.effective_params() * np.log(ndata)
        return ScoredKernel(k_opt, output.nll, laplace_nle, BIC, output.noise_hyp)  

def replace_defaults(param_vector, sd):
    #### FIXME - remove dependence on special value of zero
    ####       - Caution - remember print, compare etc when making the change (e.g. just replacing 0 with None would cause problems later)
    '''Replaces zeros in a list with Gaussians'''
    return [np.random.normal(scale=sd) if p == 0 else p for p in param_vector]

def add_random_restarts_single_kernel(kernel, n_rand, sd, data_shape):
    '''Returns a list of kernels with random restarts for default values'''
    #return [kernel] + list(itertools.repeat(kernel.family().from_param_vector(replace_defaults(kernel.param_vector(), sd)), n_rand))
    return [kernel] + list(map(lambda unused : kernel.family().from_param_vector(kernel.default_params_replaced(sd=sd, data_shape=data_shape)), [None] * n_rand))

def add_random_restarts(kernels, n_rand=1, sd=4, data_shape=None):    
    '''Augments the list to include random restarts of all default value parameters'''
    return [k_rand for kernel in kernels for k_rand in add_random_restarts_single_kernel(kernel, n_rand, sd, data_shape)]
