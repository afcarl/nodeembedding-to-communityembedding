__author__ = 'ando'
import configparser
import logging
import os
import random
import sys
from multiprocessing import cpu_count


import numpy as np
import psutil

from ADSCModel.model import Model
from ADSCModel.context_embeddings import Context2Vec
from ADSCModel.node_embeddings import Node2Vec
import ADSCModel.community_embeddings as Com2Vec

import utils.IO_utils as io_utils
import utils.graph_utils as graph_utils


p = psutil.Process(os.getpid())
try:
    p.set_cpu_affinity(list(range(cpu_count())))
except AttributeError:
    try:
        p.cpu_affinity(list(range(cpu_count())))
    except AttributeError:
        pass


#Setting the logger parameters

level = logging.DEBUG
logger = logging.getLogger("adsc")
logger.setLevel(level)

LOGFORMAT = "%(asctime).19s %(levelname)s %(filename)s: %(lineno)s %(message)s"

prop = configparser.ConfigParser()
prop.read('conf.ini')



def process_context(context_learner, model, walks, _lambda1=1.0, _lambda2=0.1, total_nodes=None):
    logger.info("Training context...")
    context_learner.train(model=model, paths=walks, _lambda1=_lambda1, _lambda2=(_lambda2/(model.k * cont_learner.window)), total_words=total_nodes)


def process_node(node_learner, model, edges, iter=1, lambda2=0.0):
    logger.info("Training node embedding...")
    node_learner.train(model, paths=edges, iter=iter, _lambda2=(lambda2/model.k))

if __name__ == "__main__":

    #Reading the input parameters form the configuration files
    number_walks = int(prop.get('MY', 'number_walks'))                      # number of walks for each node
    walk_length = int(prop.get('MY', 'walk_length'))                        # length of each walk
    window_size = int(prop.get('MY', 'window_size'))                        # windows size used to compute the context embedding
    negative = int(prop.get('MY', 'negative'))                              # number of negative sample
    representation_size = int(prop.get('MY', 'representation_size'))        # size of the embedding
    num_workers = int(prop.get('MY', 'num_workers'))                        # number of thread
    num_iter = int(prop.get('MY', 'num_iter'))                              # number of iteration

    input_file = prop.get('MY', 'input_file_name')                          # name of the input file
    output_file = prop.get('MY', 'input_file_name')                         # name of the output file

    lambda_1_val = float(prop.get('MY', 'lambda_1'))                        # alpha parameter for O2
    lambda_2_val = float(prop.get('MY', 'lambda_2'))                        # beta parameter for O3
    down_sample = float(prop.get('MY', 'down_sample'))


    walks_filebase = 'data/' + output_file + ".walks"                       # where read/write the sampled path
    sampling_path = prop.get('MY', 'sampling_path') == 'True'               # execute sampling of new walks
    pretraining = prop.get('MY', 'pretraining') == 'True'                   # execute pretraining



    #CONSTRUCT THE GRAPH
    G = graph_utils.load_adjacencylist('data/' + input_file + '/' + input_file + '.adjlist', True)

    # Sampling the random walks for context
    walk_files = None
    if sampling_path:
        logger.debug("sampling the paths")
        walk_files = graph_utils.write_walks_to_disk(G, walks_filebase,
                                                     num_paths=number_walks,
                                                     path_length=walk_length,
                                                     alpha=0,
                                                     rand=random.Random(9999999999),
                                                     num_workers=num_workers)
    else:
        walk_files = [walks_filebase + '.' + str(i) for i in range(number_walks)]

    vertex_counts = None
    if down_sample:
        vertex_counts = graph_utils.count_textfiles(walk_files, num_workers)
    else:
        vertex_counts = G.degree(G.nodes_iter())

    model = Model(G=G,
                  size=representation_size,
                  min_count=0,
                  table_size=1000000,
                  path_labels=input_file + '/' + input_file,
                  vocabulary_counts=vertex_counts,
                  downsampling=down_sample)

    #Learning algorithm
    node_learner = Node2Vec(workers=num_workers, negative=negative)
    cont_learner = Context2Vec(window=window_size, workers=num_workers, negative=negative)


    context_total_path = G.number_of_nodes() * number_walks * walk_length
    logger.debug("context_total_node: %d" % (context_total_path))

    # Sampling edges for node embedding
    edges = np.array(G.edges())

    #####################
    #   INIT MODEL      #
    #####################

    if pretraining:
        logger.info("Pre-train the model")
        process_node(node_learner, model,  edges, iter=int(context_total_path/G.number_of_edges()), lambda2=0.0)
        process_context(cont_learner, model, graph_utils.combine_files_iter(walk_files), _lambda1=1.0, _lambda2=0.0, total_nodes=context_total_path)
        model.save(file_name=output_file+'_comEmb_init')
        io_utils.save_embedding(model.node_embedding, file_name=output_file+'_comEmb_init_nodeembedding')
    else:
        model.load_model(file_name=output_file+'_comEmb_init')

    logger.info('\n_______________________________________\n')
    logger.info('using down_sample: %.5f lambda 1:%.4f \t lambda 2:%.4f' % (down_sample, lambda_1_val, lambda_2_val))

    ###########################
    #   EMBEDDING LEARNING    #
    ###########################
    for _ in range(num_iter):
        Com2Vec.training(model, is_debug=False, plot=False)
        process_node(node_learner, model, edges, iter=int(context_total_path/G.number_of_edges()), lambda2=lambda_2_val)
        process_context(cont_learner, model, graph_utils.combine_files_iter(walk_files), _lambda1=lambda_1_val,
                        _lambda2=lambda_2_val, total_nodes=context_total_path)

    io_utils.save_embedding(model.node_embedding, file_name=output_file + "_comEmb" +
                                                            "_l1-"+str(lambda_1_val) +
                                                            "_l2-"+str(lambda_2_val) +
                                                            "_ds-"+ str(down_sample))