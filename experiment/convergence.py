from evaluation.general_performance import evaluate, evaluate_explanation
from prediction.predictor import predict_elementwise, predict_explanation
from utils.io import save_dataframe_csv
from utils.modelnames import models, explanable_models
from utils.progress import WorkSplitter
from utils.reformat import to_sparse_matrix
from utils.sampler import Negative_Sampler

import json
import pandas as pd
import tensorflow.compat.v1 as tf
tf.disable_eager_execution()


def converge(num_users, num_items, user_col, item_col, rating_col, keyphrase_vector_col, df_train, df_test, keyphrase_names, df, table_path, file_name, epoch=10):
    progress = WorkSplitter()

    results = pd.DataFrame(columns=['model', 'rank', 'num_layers', 'train_batch_size', 'predict_batch_size',
                                    'lambda', 'topK', 'learning_rate', 'epoch', 'negative_sampling_size', 'optimizer'])

    for run in range(3):

        for idx, row in df.iterrows():
            row = row.to_dict()
            if row['model'] not in models:
                continue

            progress.section(json.dumps(row))

            row['metric'] = ['R-Precision', 'NDCG', 'Clicks', 'Recall', 'Precision', 'MAP']
            row['topK'] = [10]

            if 'optimizer' not in row.keys():
                row['optimizer'] = 'Adam'

            negative_sampler = Negative_Sampler(df_train[[user_col,
                                                          item_col,
                                                          keyphrase_vector_col]],
                                                user_col,
                                                item_col,
                                                rating_col,
                                                keyphrase_vector_col,
                                                num_items=num_items,
                                                batch_size=row['train_batch_size'],
                                                num_keyphrases=len(keyphrase_names),
                                                negative_sampling_size=row['negative_sampling_size'])

            model = models[row['model']](num_users=num_users,
                                         num_items=num_items,
                                         text_dim=len(keyphrase_names),
                                         embed_dim=row['rank'],
                                         num_layers=row['num_layers'],
                                         negative_sampler=negative_sampler,
                                         lamb=row['lambda'],
                                         learning_rate=row['learning_rate'])

            batches = negative_sampler.get_batches()

            epoch_batch = 10

            for i in range(epoch//epoch_batch):
                if i == 0:
                    model.train_model(df_train,
                                      user_col,
                                      item_col,
                                      rating_col,
                                      epoch=epoch_batch,
                                      batches=batches,
                                      init_embedding=True)
                else:
                    model.train_model(df_train,
                                      user_col,
                                      item_col,
                                      rating_col,
                                      epoch=epoch_batch,
                                      batches=batches,
                                      init_embedding=False)

                prediction, explanation = predict_elementwise(model,
                                                              df_train,
                                                              user_col,
                                                              item_col,
                                                              row['topK'][0],
                                                              batch_size=row['predict_batch_size'],
                                                              enable_explanation=False,
                                                              keyphrase_names=keyphrase_names)

                R_test = to_sparse_matrix(df_test,
                                          num_users,
                                          num_items,
                                          user_col,
                                          item_col,
                                          rating_col)

                result = evaluate(prediction, R_test, row['metric'], row['topK'])

                # Note Finished yet
                result_dict = {'model': row['model'],
                               'rank': row['rank'],
                               'num_layers': row['num_layers'],
                               'train_batch_size': row['train_batch_size'],
                               'predict_batch_size': row['predict_batch_size'],
                               'lambda': row['lambda'],
                               'topK': row['topK'][0],
                               'learning_rate': row['learning_rate'],
                               'epoch': (i+1)*epoch_batch,
                               'negative_sampling_size': row['negative_sampling_size'],
                               'optimizer': row['optimizer']}

                for name in result.keys():
                    result_dict[name] = round(result[name][0], 4)
                results = results.append(result_dict, ignore_index=True)
                print("result is \n {}".format(results))

            model.sess.close()
            tf.reset_default_graph()

            save_dataframe_csv(results, table_path, file_name)

    return results


def explanation_converge(num_users, num_items, user_col, item_col, rating_col, keyphrase_vector_col, df_train, df_test, keyphrase_names, df, table_path, file_name, epoch=10):
    progress = WorkSplitter()

    results = pd.DataFrame(columns=['model', 'rank', 'num_layers', 'train_batch_size', 'predict_batch_size',
                                    'lambda', 'topK', 'learning_rate', 'epoch', 'negative_sampling_size', 'optimizer'])

    for run in range(3):

        for idx, row in df.iterrows():
            row = row.to_dict()
            if row['model'] not in explanable_models:
                continue

            progress.section(json.dumps(row))

            row['metric'] = ['NDCG', 'Recall', 'Precision', 'MAP']
            row['topK'] = [10]

            if 'optimizer' not in row.keys():
                row['optimizer'] = 'Adam'

            negative_sampler = Negative_Sampler(df_train[[user_col,
                                                          item_col,
                                                          keyphrase_vector_col]],
                                                user_col,
                                                item_col,
                                                rating_col,
                                                keyphrase_vector_col,
                                                num_items=num_items,
                                                batch_size=row['train_batch_size'],
                                                num_keyphrases=len(keyphrase_names),
                                                negative_sampling_size=1)
            # explanation does not sensitive to negative samples

            model = models[row['model']](num_users=num_users,
                                         num_items=num_items,
                                         text_dim=len(keyphrase_names),
                                         embed_dim=row['rank'],
                                         num_layers=row['num_layers'],
                                         negative_sampler=negative_sampler,
                                         lamb=row['lambda'],
                                         learning_rate=row['learning_rate'])

            batches = negative_sampler.get_batches()

            epoch_batch = 10

            for i in range(epoch//epoch_batch):

                if i == 0:
                    model.train_model(df_train,
                                      user_col,
                                      item_col,
                                      rating_col,
                                      epoch=epoch_batch,
                                      batches=batches,
                                      init_embedding=True)
                else:
                    model.train_model(df_train,
                                      user_col,
                                      item_col,
                                      rating_col,
                                      epoch=epoch_batch,
                                      batches=batches,
                                      init_embedding=False)

                df_valid_explanation = predict_explanation(model,
                                                           df_test,
                                                           user_col,
                                                           item_col,
                                                           topk_keyphrase=row['topK'][0])

                result = evaluate_explanation(df_valid_explanation,
                                              df_test,
                                              row['metric'],
                                              row['topK'],
                                              user_col,
                                              item_col,
                                              rating_col,
                                              keyphrase_vector_col)

                # Note Finished yet
                result_dict = {'model': row['model'],
                               'rank': row['rank'],
                               'num_layers': row['num_layers'],
                               'train_batch_size': row['train_batch_size'],
                               'predict_batch_size': row['predict_batch_size'],
                               'lambda': row['lambda'],
                               'topK': row['topK'][0],
                               'learning_rate': row['learning_rate'],
                               'epoch': (i+1)*epoch_batch,
                               'negative_sampling_size': row['negative_sampling_size'],
                               'optimizer': row['optimizer']}

                for name in result.keys():
                    result_dict[name] = round(result[name][0], 4)
                results = results.append(result_dict, ignore_index=True)
                print("result is \n {}".format(results))

            model.sess.close()
            tf.reset_default_graph()

            save_dataframe_csv(results, table_path, file_name)

    return results
