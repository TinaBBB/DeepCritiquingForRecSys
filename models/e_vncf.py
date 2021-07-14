from tqdm import tqdm
from utils.reformat import to_sparse_matrix, to_svd

import tensorflow.compat.v1 as tf
tf.disable_eager_execution()
from tensorflow.compat.v1.train import AdamOptimizer

class EVNCF(object):
    def __init__(self,
                 num_users,
                 num_items,
                 text_dim,
                 embed_dim,
                 num_layers,
                 negative_sampler,
                 lamb=0.01,
                 learning_rate=1e-4,
                 optimizer=AdamOptimizer,
                 **unused):
        self.num_users = num_users
        self.num_items = num_items
        self.text_dim = text_dim
        self.embed_dim = embed_dim
        self.num_layers = num_layers
        self.negative_sampler = negative_sampler
        self.lamb = lamb
        self.learning_rate = learning_rate
        self.optimizer = optimizer
        self.get_graph()
        self.sess = tf.Session()
        self.sess.run(tf.global_variables_initializer())
        # print([n.name for n in tf.get_default_graph().as_graph_def().node])
        # tf.summary.FileWriter('./graphs', self.sess.graph)

    def get_graph(self):

        self.users_index = tf.placeholder(tf.int32, [None], name='user_id')
        self.items_index = tf.placeholder(tf.int32, [None], name='item_id')
        self.rating = tf.placeholder(tf.int32, [None], name='rating')
        self.keyphrase_vector = tf.placeholder(tf.int32, [None, self.text_dim], name='keyphrases_vector')
        self.modified_keyphrase = tf.placeholder(tf.float32, [None, self.text_dim], name='modified_keyphrases')
        self.sampling = tf.placeholder(tf.bool)
        self.corruption = tf.placeholder(tf.float32)

        with tf.variable_scope("embeddings"):
            self.user_embeddings = tf.Variable(tf.random_normal([self.num_users, self.embed_dim],
                                                                stddev=1 / (self.embed_dim ** 0.5),
                                                                dtype=tf.float32), trainable=True)

            self.item_embeddings = tf.Variable(tf.random_normal([self.num_items, self.embed_dim],
                                                                stddev=1 / (self.embed_dim ** 0.5),
                                                                dtype=tf.float32), trainable=True)

            users = tf.nn.embedding_lookup(self.user_embeddings, self.users_index, name="user_lookup")
            items = tf.nn.embedding_lookup(self.item_embeddings, self.items_index, name="item_lookup")

        with tf.variable_scope("residual"):
            hi = tf.concat([users, items], axis=1)

            hi = tf.nn.dropout(hi, 1 - self.corruption)

            for i in range(self.num_layers):
                ho = tf.layers.dense(inputs=hi, units=self.embed_dim*4,
                                     kernel_regularizer=tf.keras.regularizers.l2(scale=self.lamb),
                                     activation=None)
                hi = ho

        with tf.variable_scope('latent'):
            self.mean = tf.nn.relu(hi[:, :self.embed_dim*2])
            logstd = tf.nn.tanh(hi[:, self.embed_dim*2:])*3
            self.stddev = tf.exp(logstd)
            epsilon = tf.random_normal(tf.shape(self.stddev))
            self.z = tf.cond(self.sampling, lambda: self.mean + self.stddev * epsilon, lambda: self.mean)

        with tf.variable_scope("prediction", reuse=False):
            rating_prediction = tf.layers.dense(inputs=self.z, units=1,
                                                kernel_regularizer=tf.keras.regularizers.l2(scale=self.lamb),
                                                activation=None, name='rating_prediction')
            keyphrase_prediction = tf.layers.dense(inputs=self.z, units=self.text_dim,
                                                   kernel_regularizer=tf.keras.regularizers.l2(scale=self.lamb),
                                                   activation=None, name='keyphrase_prediction')

            self.rating_prediction = rating_prediction
            self.keyphrase_prediction = keyphrase_prediction

        with tf.variable_scope("losses"):
            keyphrase_condition = tf.stop_gradient(tf.cast(tf.reduce_max(self.keyphrase_vector, axis=1), tf.float32))

            with tf.variable_scope('kl-divergence'):
                kl = self._kl_diagnormal_stdnormal(self.mean, logstd)

            with tf.variable_scope("rating_loss"):
                # rating_loss = tf.losses.sigmoid_cross_entropy(multi_class_labels=tf.reshape(self.rating, [-1, 1]),
                #                                               logits=self.rating_prediction)
                rating_loss = tf.losses.mean_squared_error(labels=tf.reshape(self.rating, [-1, 1]),
                                                           predictions=self.rating_prediction)

            with tf.variable_scope("keyphrase_loss"):
                keyphrase_loss = tf.losses.mean_squared_error(labels=self.keyphrase_vector,
                                                              predictions=self.keyphrase_prediction) * keyphrase_condition

            with tf.variable_scope("l2"):
                l2_loss = tf.losses.get_regularization_loss()

            self.loss = (tf.reduce_mean(rating_loss)
                         + tf.reduce_mean(keyphrase_loss)
                         + 0.01 * kl
                         + l2_loss
                         )

        with tf.variable_scope('optimizer'):
            self.train = self.optimizer(learning_rate=self.learning_rate).minimize(self.loss)

    @staticmethod
    def _kl_diagnormal_stdnormal(mu, log_std):
        var_square = tf.exp(2 * log_std)
        kl = 0.5 * tf.reduce_mean(tf.square(mu) + var_square - 1. - 2 * log_std)

        return kl

    def train_model(self, df, user_col, item_col, rating_col, epoch=100,
                    batches=None, init_embedding=True, **unused):

        if init_embedding:
            self.get_user_item_embeddings(df, user_col, item_col, rating_col)

        if batches is None:
            batches = self.negative_sampler.get_batches()

        # Training
        pbar = tqdm(range(epoch))
        for i in pbar:
            for batch in batches:
                feed_dict = {self.users_index: batch[0],
                             self.items_index: batch[1],
                             self.corruption: 0.1,
                             self.rating: batch[2],
                             self.keyphrase_vector: batch[3].todense(),
                             self.sampling: True}

                training, loss = self.sess.run([self.train, self.loss], feed_dict=feed_dict)
                pbar.set_description("loss:{}".format(loss))

            #if (i+1) % 5 == 0:
            batches = self.negative_sampler.get_batches()

    def predict(self, inputs):
        user_index = inputs[:, 0]
        item_index = inputs[:, 1]
        feed_dict = {self.users_index: user_index,
                     self.items_index: item_index,
                     self.sampling: False,
                     self.corruption: 0}
        return self.sess.run([self.rating_prediction,
                              self.keyphrase_prediction],
                             feed_dict=feed_dict)

    def get_user_item_embeddings(self, df, user_col, item_col, rating_col):
        R = to_sparse_matrix(df, self.num_users, self.num_items, user_col, item_col, rating_col)
        user_embedding, item_embedding = to_svd(R, self.embed_dim)
        self.sess.run([self.user_embeddings.assign(user_embedding),
                       self.item_embeddings.assign(item_embedding)])

    def save_model(self, path, name):
        saver = tf.train.Saver()
        save_path = saver.save(self.sess, "{}/{}/model.ckpt".format(path, name))
        print("Model saved in path: %s" % save_path)

    def load_model(self, path, name):
        saver = tf.train.Saver()
        saver.restore(self.sess, "{}/{}/model.ckpt".format(path, name))
        print("Model restored.")

