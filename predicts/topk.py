from tqdm import tqdm

import numpy as np
import pandas as pd


def elementwisepredictor(model, train, user_col, item_col, topk,
                         batch_size=1000, explain=False, key_names=None, topk_key=10):

    prediction = []
    explanation = []

    num_user = model.num_users
    num_item = model.num_items

    for i in tqdm(range(num_user)):

        input_batch = []
        output_batch = []
        rated_item = train[train[user_col] == i][item_col].values
        for j in range(num_item):
            if j in rated_item:
                continue
            input_batch.append([i, j])
            if (j + 1) % batch_size == 0 or (j + 1) == num_item:
                inputs = np.array(input_batch)
                output_batch.append(np.concatenate([inputs] + model.predict(inputs), axis=1))
                input_batch = []

        user_output = np.concatenate(output_batch, axis=0)

        user_output = user_output[user_output[:, 2].argsort()[::-1][:topk]]

        candidates = user_output[:, 1].astype(int)

        prediction.append(candidates)
        if explain:
            for j in range(topk):
                candidate_idx = np.argsort(user_output[j, 3:])[::-1][:topk_key]
                candidate_keys = key_names[candidate_idx]
                explanation.append({'UserIndex': i, 'ItemIndex': candidates[j],
                                    'ExplanIndex': candidate_idx, 'Explanation': candidate_keys})

    return np.array(prediction), pd.DataFrame(explanation)

