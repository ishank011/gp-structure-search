'''
Main file for setting up experiments, and compiling results.

@authors: David Duvenaud (dkd23@cam.ac.uk)
          James Robert Lloyd (jrl44@cam.ac.uk)
          Roger Grosse (rgrosse@mit.edu)
          
Created Jan 2013          
'''

from collections import namedtuple
from itertools import izip
import numpy as np
nax = np.newaxis
import os
import random
import re
import scipy.io

import flexiblekernel as fk
from flexiblekernel import ScoredKernel
import grammar
import gpml
import utils.latex
import cblparallel
from cblparallel.util import mkstemp_safe
import job_controller as jc
import utils.misc

FROBENIUS_CUTOFF = 0.01; # How different two matrices have to be to be considered different.

def remove_duplicates(kernels, X, n_eval=250, local_computation=True, verbose=True):
    '''
    Test the top n_eval performing kernels for equivalence, in terms of their covariance matrix evaluated on training inputs
    Assumes kernels is a list of ScoredKernel objects
    '''
    # Because this is slow, we can do it locally.
    local_computation = True

    kernels = sorted(kernels, key=ScoredKernel.score, reverse=False)
    
    # Find covariance distance for top n_eval
    n_eval = min(n_eval, len(kernels))
    distance_matrix = jc.covariance_distance(kernels[:n_eval], X, local_computation=local_computation, verbose=verbose)
    
    # Remove similar kernels
    #### TODO - What is a good heuristic for determining equivalence?
    ####      - Currently using Frobenius norm - truncate if Frobenius norm is below a fraction of the average
    cut_off = distance_matrix.mean() * FROBENIUS_CUTOFF
    equivalence_graph = distance_matrix < cut_off
    # For all kernels (best first)
    for i in range(n_eval):
        # For all other worse kernels
        for j in range(i+1, n_eval):
            if equivalence_graph[i,j]:
                # Destroy the inferior duplicate
                kernels[j] = None

    kernels = [k for k in kernels if k is not None]
    kernels = sorted(kernels, key=ScoredKernel.score, reverse=True)
    return kernels
 
def remove_nan_scored_kernels(scored_kernels):    
    return [k for k in scored_kernels if not np.isnan(k.score())] 
    
def perform_kernel_search(X, y, D, experiment_data_file_name, results_filename, exp):
    '''Search for the best kernel, in parallel on fear or local machine.'''
    
    # Initialise random seeds - randomness may be used in e.g. data subsetting
    utils.misc.set_all_random_seeds(exp.random_seed)

    # Initialise kernels to be all base kernels along all dimensions.
    current_kernels = list(fk.base_kernels(D, exp.base_kernels))
    print 'Dimension: ', str(D)
    
    # Create location, scale and minimum period parameters to pass around for initialisations
    data_shape = {}
    data_shape['input_location'] = [np.mean(X[:,dim]) for dim in range(X.shape[1])]
    data_shape['output_location'] = np.mean(y)
    data_shape['input_scale'] = np.log([np.std(X[:,dim]) for dim in range(X.shape[1])])
    data_shape['output_scale'] = np.log(np.std(y)) 
    # Initialise period at a multiple of the shortest / average distance between points, to prevent Nyquist problems.
    if exp.use_min_period:
        data_shape['min_period'] = np.log([max(exp.period_heuristic * utils.misc.min_abs_diff(X[:,i]), exp.period_heuristic * np.ptp(X[:,i]) / X.shape[0]) for i in range(X.shape[1])])
    else:
        data_shape['min_period'] = None
    #### TODO - make the below and above more elegant
    if exp.use_constraints:
        data_shape['min_alpha'] = exp.alpha_heuristic
        data_shape['min_lengthscale'] = exp.lengthscale_heuristic + data_shape['input_scale']
    else:
        data_shape['min_alpha'] = None
        data_shape['min_lengthscale'] = None
    
    all_results = []
    results_sequence = []     # List of lists of results, indexed by level of expansion.
    
    # Perform search
    for depth in range(exp.max_depth):
        
        if exp.debug==True:
            current_kernels = current_kernels[0:4]
             
        # Add random restarts to kernels
        current_kernels = fk.add_random_restarts(current_kernels, exp.n_rand, exp.sd, data_shape=data_shape)
        # Score the kernels
        new_results = jc.evaluate_kernels(current_kernels, X, y, verbose=exp.verbose, local_computation=exp.local_computation,
                                          zip_files=False, max_jobs=exp.max_jobs, iters=exp.iters, zero_mean=exp.zero_mean, random_seed=exp.random_seed)
        # Enforce the period heuristic
        #### TODO - Concept of parameter constraints is more general than this - make it so
        if exp.use_min_period:
            new_results = [sk for sk in new_results if not sk.k_opt.out_of_bounds(data_shape)]
        # Some of the scores may have failed - remove nans to prevent sorting algorithms messing up
        new_results = remove_nan_scored_kernels(new_results)
        assert(len(new_results) > 0) # FIXME - Need correct control flow if this happens 
        # Sort the new all_results
        new_results = sorted(new_results, key=ScoredKernel.score, reverse=True)
        
        print 'All new results:'
        for result in new_results:
            print result.nll, result.laplace_nle, result.bic_nle, result.k_opt.pretty_print()
            
        # Remove near duplicates from these all_results (top m all_results only for efficiency)
        if exp.k > 1:
            # Only remove duplicates if they affect the search
            new_results = remove_duplicates(new_results, X, local_computation=exp.local_computation, verbose=exp.verbose)

        print 'All new results after duplicate removal:'
        for result in new_results:
            print result.nll, result.laplace_nle, result.bic_nle, result.k_opt.pretty_print()

        all_results = all_results + new_results
        all_results = sorted(all_results, key=ScoredKernel.score, reverse=True)

        results_sequence.append(all_results)
        if exp.verbose:
            print 'Printing all results'
            for result in all_results:
                print result.nll, result.laplace_nle, result.bic_nle, result.k_opt.pretty_print()
        
        # Extract the best k kernels from the new all_results
        best_results = sorted(new_results, key=ScoredKernel.score)[0:exp.k]
        best_kernels = [r.k_opt for r in best_results]
        current_kernels = grammar.expand_kernels(D, best_kernels, verbose=exp.verbose, debug=exp.debug, base_kernels=exp.base_kernels)
        
        if exp.debug==True:
            current_kernels = current_kernels[0:4]

        # Write all_results to a temporary file at each level.
        all_results = sorted(all_results, key=ScoredKernel.score, reverse=True)
        with open(results_filename + '.unfinished', 'w') as outfile:
            outfile.write('Experiment all_results for\n datafile = %s\n\n %s \n\n' \
                          % (experiment_data_file_name, experiment_fields_to_str(exp)))
            for (i, all_results) in enumerate(results_sequence):
                outfile.write('\n%%%%%%%%%% Level %d %%%%%%%%%%\n\n' % i)
                if exp.verbose_results:
                    for result in all_results:
                        print >> outfile, result  
                else:
                    # Only print top k kernels - i.e. those used to seed the next level of the search
                    for result in best_results:
                        print >> outfile, result 
    
    # Rename temporary results file to actual results file                
    os.rename(results_filename + '.unfinished', results_filename)

def parse_results( results_filename, max_level=None ):
    '''
    Returns the best kernel in an experiment output file as a ScoredKernel
    '''
    # Read relevant lines of file
    lines = []
    with open(results_filename) as results_file:
        for line in results_file:
            if line.startswith("ScoredKernel"):
                lines.append(line)
            elif (not max_level is None) and (len(re.findall('Level [0-9]+', line)) > 0):
                level = int(line.split(' ')[2])
                if level > max_level:
                    break
    #result_tuples = [fk.repr_string_to_kernel(line.strip()) for line in open(results_filename) if line.startswith("ScoredKernel")]
    result_tuples = [fk.repr_string_to_kernel(line.strip()) for line in lines]
    best_tuple = sorted(result_tuples, key=ScoredKernel.score)[0]
    return best_tuple

def gen_all_datasets(dir):
    """Looks through all .mat files in a directory, or just returns that file if it's only one."""
    if dir.endswith(".mat"):
        (r, f) = os.path.split(dir)
        (f, e) = os.path.splitext(f)
        return [(r, f)]
    
    file_list = []
    for r,d,f in os.walk(dir):
        for files in f:
            if files.endswith(".mat"):
                file_list.append((r, files.split('.')[-2]))
    file_list.sort()
    return file_list

# Defines a class that keeps track of all the options for an experiment.
# Maybe more natural as a dictionary to handle defaults - but named tuple looks nicer with . notation
class Experiment(namedtuple("Experiment", 'description, data_dir, max_depth, random_order, k, debug, local_computation, n_rand, sd, max_jobs, verbose, make_predictions, skip_complete, results_dir, iters, base_kernels, zero_mean, verbose_results, random_seed, use_min_period, period_heuristic, use_constraints, alpha_heuristic, lengthscale_heuristic')):
    def __new__(cls, 
                data_dir,                     # Where to find the datasets.
                results_dir,                  # Where to write the results.
                description = 'no description',
                max_depth = 10,               # How deep to run the search.
                random_order = False,         # Randomize the order of the datasets?
                k = 1,                        # Keep the k best kernels at every iteration.  1 => greedy search.
                debug = False,
                local_computation = True,     # Run experiments locally, or on the cloud.
                n_rand = 2,                   # Number of random restarts.
                sd = 4,                       # Standard deviation of random restarts.
                max_jobs=500,                 # Maximum number of jobs to run at once on cluster.
                verbose=False,
                make_predictions=False,       # Whether or not to forecast on a test set.
                skip_complete=True,           # Whether to re-run already completed experiments.
                iters=100,                    # How long to optimize hyperparameters for.
                base_kernels='SE,RQ,Per,Lin,Const',
                zero_mean=True,               # If false, use a constant mean function - cannot be used with the Const kernel
                verbose_results=False,        # Whether or not to record all kernels tested
                random_seed=0,
		        use_min_period=True,          # Whether to not let the period in a periodic kernel be smaller than the minimum period.
                period_heuristic=10,
		        use_constraints=False,        # Place hard constraints on some parameter values? #### TODO - should be replaced with a prior / more Bayesian analysis
                alpha_heuristic=-2,           # Minimum alpha value for RQ kernel
                lengthscale_heuristic=-4.5):  # Minimum lengthscale     
        return super(Experiment, cls).__new__(cls, description, data_dir, max_depth, random_order, k, debug, local_computation, n_rand, sd, max_jobs, verbose, make_predictions, skip_complete, results_dir, iters, base_kernels, zero_mean, verbose_results, random_seed, use_min_period, period_heuristic, use_constraints, alpha_heuristic, lengthscale_heuristic)

def experiment_fields_to_str(exp):
    str = "Running experiment:\n"
    for field, val in izip(exp._fields, exp):
        str += "%s = %s,\n" % (field, val)
    return str

def run_experiment_file(filename):
    """
    This is intended to be the function that's called to initiate a series of experiments.
    """       
    expstring = open(filename, 'r').read()
    exp = eval(expstring)
    print experiment_fields_to_str(exp)
    
    data_sets = list(gen_all_datasets(exp.data_dir))
    
    # Create results directory if it doesn't exist.
    if not os.path.isdir(exp.results_dir):
        os.makedirs(exp.results_dir)

    if exp.random_order:
        random.shuffle(data_sets)

    for r, file in data_sets:
        # Check if this experiment has already been done.
        output_file = os.path.join(exp.results_dir, file + "_result.txt")
        if not(exp.skip_complete and (os.path.isfile(output_file))):
            print 'Experiment %s' % file
            print 'Output to: %s' % output_file
            data_file = os.path.join(r, file + ".mat")

            perform_experiment(data_file, output_file, exp)
            print "Finished file %s" % file
        else:
            print 'Skipping file %s' % file

    #os.system('reset')  # Stop terminal from going invisible.   

def generate_model_fits(filename):
    """
    This is intended to be the function that's called to initiate a series of experiments.
    """       
    expstring = open(filename, 'r').read()
    exp = eval(expstring)
    exp = exp._replace(local_computation = True)
    print experiment_fields_to_str(exp)
    
    data_sets = list(gen_all_datasets(exp.data_dir))
    
    # Create results directory if it doesn't exist.
    if not os.path.isdir(exp.results_dir):
        os.makedirs(exp.results_dir)

    if exp.random_order:
        random.shuffle(data_sets)

    for r, file in data_sets:
        # Check if this experiment has already been done.
        output_file = os.path.join(exp.results_dir, file + "_result.txt")
        if os.path.isfile(output_file):
            print 'Experiment %s' % file
            print 'Output to: %s' % output_file
            data_file = os.path.join(r, file + ".mat")

            calculate_model_fits(data_file, output_file, exp )
            print "Finished file %s" % file
        else:
            print 'Skipping file %s' % file

    os.system('reset')  # Stop terminal from going invisible. 
    
def perform_experiment(data_file, output_file, exp):
    
    if exp.make_predictions:        
        X, y, D, Xtest, ytest = gpml.load_mat(data_file, y_dim=1)
        prediction_file = os.path.join(exp.results_dir, os.path.splitext(os.path.split(data_file)[-1])[0] + "_predictions.mat")
    else:
        X, y, D = gpml.load_mat(data_file, y_dim=1)
        
    perform_kernel_search(X, y, D, data_file, output_file, exp)
    best_scored_kernel = parse_results(output_file)
    
    if exp.make_predictions:
        predictions = jc.make_predictions(X, y, Xtest, ytest, best_scored_kernel, local_computation=exp.local_computation,
                                          max_jobs=exp.max_jobs, verbose=exp.verbose, zero_mean=exp.zero_mean, random_seed=exp.random_seed)
        scipy.io.savemat(prediction_file, predictions, appendmat=False)
        
    #os.system('reset')  # Stop terminal from going invisible.
    
def calculate_model_fits(data_file, output_file, exp):
         
    prediction_file = os.path.join(exp.results_dir, os.path.splitext(os.path.split(data_file)[-1])[0] + "_predictions.mat")
    X, y, D, = gpml.load_mat(data_file, y_dim=1)
    Xtest = X
    ytest = y
        
    best_scored_kernel = parse_results(output_file)
    
    predictions = jc.make_predictions(X, y, Xtest, ytest, best_scored_kernel, local_computation=exp.local_computation,
                                      max_jobs=exp.max_jobs, verbose=exp.verbose, zero_mean=exp.zero_mean, random_seed=exp.random_seed)
    scipy.io.savemat(prediction_file, predictions, appendmat=False)
        
    os.system('reset')  # Stop terminal from going invisible.
   

def run_debug_kfold():
    """This is a quick debugging function."""
    run_experiment_file('../experiments/debug_example.py')
    
#def compute_SNRs(experiment_file):
#    expstring = open(filename, 'r').read()
#    exp = eval(expstring)
#    print experiment_fields_to_str(exp)
#    data_sets = list(gen_all_datasets(exp.data_dir))
#    for r, file in data_sets:
#        data_file = os.path.join(r, file + ".mat")
    
