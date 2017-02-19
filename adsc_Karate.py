__author__ = 'ando'
import configparser
import os
import random
from multiprocessing import cpu_count


import numpy as np
import psutil

from ADSCModel.model import Model
from ADSCModel.context_embeddings import Context2Vec
from ADSCModel.node_embeddings import Node2Vec
from ADSCModel.community_embeddings import Community2Vec

import utils.graph_utils as graph_utils
import utils.plot_utils as plot_utils
import timeit



p = psutil.Process(os.getpid())
try:
    p.set_cpu_affinity(list(range(cpu_count())))
except AttributeError:
    try:
        p.cpu_affinity(list(range(cpu_count())))
    except AttributeError:
        pass

prop = configparser.ConfigParser()
prop.read('conf.ini')



def process_context(context_learner, model, walks, total_nodes, _lambda1=1.0, _lambda2=0.1):
    print("Training context...")
    return context_learner.train(model=model, paths=walks, total_words=total_nodes, _lambda1=_lambda1, _lambda2=(_lambda2/(model.k * cont_learner.window_size)))


def process_node(node_learner, model, edges, iter=1, lambda2=0.0):
    print("Training node embedding...")
    return node_learner.train(model, edges=edges, iter=iter, _lambda2=(lambda2/model.k))

if __name__ == "__main__":

    #Reading the input parameters form the configuration files
    number_walks = 10                      # number of walks for each node
    walk_length = 10                        # length of each walk
    window_size = 3                        # windows size used to compute the context embedding
    negative = 3                              # number of negative sample
    representation_size = 2        # size of the embedding
    num_workers = 4                        # number of thread
    num_iter = 5                              # number of iteration
    reg_covar = 0.00001                          # regularization coefficient to ensure positive covar
    input_file = 'karate'                          # name of the input file
    output_file = 'karate'                         # name of the output file

    lambda_1_val = 1
    lambda_2_val = 0.0005

    walks_filebase = 'data/' + output_file + ".walks"                       # where read/write the sampled path
    sampling_path = prop.getboolean('MY', 'sampling_path')                  # execute sampling of new walks



    #CONSTRUCT THE GRAPH
    G = graph_utils.load_adjacencylist('data/' + input_file + '/' + input_file + '.adjlist', True)
    node_color = plot_utils.graph_plot(G=G, save=False, show=False)

    # Sampling the random walks for context
    walk_files = None
    if sampling_path:
        print("sampling the paths")
        walk_files = graph_utils.write_walks_to_disk(G, walks_filebase,
                                                     num_paths=number_walks,
                                                     path_length=walk_length,
                                                     alpha=0,
                                                     rand=random.Random(9999999999),
                                                     num_workers=num_workers)
    else:
        walk_files = [walks_filebase + '.' + str(i) for i in range(number_walks)]



    #Learning algorithm
    node_learner = Node2Vec(workers=num_workers, negative=negative)
    cont_learner = Context2Vec(window_size=window_size, workers=num_workers, negative=negative)
    comm_learner = Community2Vec(reg_covar=reg_covar)



    vertex_counts = G.degree(G.nodes_iter())

    model = Model(G=G,
                  size=representation_size,
                  min_count=0,
                  table_size=5000000,
                  input_file=input_file + '/' + input_file,
                  vocabulary_counts=vertex_counts,
                  downsampling=0)

    model.node_color = node_color

    context_total_path = G.number_of_nodes() * number_walks * walk_length
    edges = np.array(G.edges())
    print("context_total_path: %d" % (context_total_path))
    print('node total edges: %d' % G.number_of_edges())

    print('\n_______________________________________\n')
    print('using lambda 1:%.4f \t lambda 2:%.4f' % (lambda_1_val, lambda_2_val))
    print('Number of community: %d' % model.k)

    ###########################
    #   EMBEDDING LEARNING    #
    ###########################
    for it in range(num_iter):
        print('\n_______________________________________\n')
        start_time = timeit.default_timer()
        if it == 0:
            process_node(node_learner, model, edges, iter=int(context_total_path/G.number_of_edges()), lambda2=0)
        else:
            process_node(node_learner, model, edges, iter=int(context_total_path / G.number_of_edges()),
                         lambda2=lambda_2_val)

        process_context(cont_learner, model, graph_utils.combine_files_iter(walk_files), total_nodes=context_total_path,
                        _lambda1=lambda_1_val, _lambda2=0)

        comm_learner.train(model)

        plot_utils.node_space_plot_2D_elipsoid(model.node_embedding, node_color, means=model.centroid,
                                               covariances=model.covariance_mat)

        model.save(path='data', file_name=output_file + "_comEmb" +
                                          "_l1-" + str(lambda_1_val) +
                                          "_l2-" + str(lambda_2_val) +
                                          "_ds-" + str(0) +
                                          "_it-" + str(it))

        print('time: %.2fs' % (timeit.default_timer() - start_time))
