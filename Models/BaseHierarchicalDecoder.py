import json
import torch
from torch import nn
import torchvision
from ClassAttention import *
from Attention import Attention
from abc import ABC, abstractmethod

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class BaseHierarchicalDecoder(nn.Module):
    """
    Decoder with continuous Outputs.
    """

    def __init__(self, attention_dim, embed_dim, decoder_dim, vocab_size, sos_embedding, nr_labels=28, hidden_dim = 512, encoder_dim=1024,
                 dropout=0.5, use_tf_as_input = 1, use_scheduled_sampling=False , scheduled_sampling_prob = 0.):
        """
        :param attention_dim: size of attention network
        :param embed_dim: embedding size
        :param decoder_dim: size of decoder's RNN
        :param vocab_size: size of vocabulary
        :param encoder_dim: feature size of encoded images
        :param dropout: dropout
        """
        super(BaseHierarchicalDecoder, self).__init__()

        self.nr_labels = nr_labels
        self.attention_dim = attention_dim
        self.embed_dim = embed_dim
        self.decoder_dim = decoder_dim
        self.vocab_size = vocab_size
        self.dropout = dropout
        self.sos_embedding = sos_embedding
        self.use_tf_as_input = use_tf_as_input
        self.use_scheduled_sampling = use_scheduled_sampling
        self.scheduled_sampling_prob = scheduled_sampling_prob
        self.hidden_dim = hidden_dim


        self.visual_attention = Attention(encoder_dim, hidden_dim, attention_dim)  # attention network

        self.label_attention = ClassAttention(nr_labels, hidden_dim, attention_dim) 

        #self.context_vector_fc = nn.Linear(encoder_dim + nr_labels, hidden_dim)
        self.context_vector_fc = nn.Linear(encoder_dim, hidden_dim)

        self.context_vector_W = nn.Linear(hidden_dim, hidden_dim)

        self.context_vector_W_h_t = nn.Linear(hidden_dim, hidden_dim)


        self.embedding = nn.Embedding(vocab_size, embed_dim)  # embedding layer
        self.dropout = nn.Dropout(p=self.dropout)
        
        self.resize_encoder_features = nn.Linear(encoder_dim, hidden_dim)
        
        self.sentence_decoder = nn.LSTMCell(hidden_dim, hidden_dim, bias=True)  # decoding LSTMCell
        self.word_decoder = nn.LSTMCell(embed_dim + embed_dim, hidden_dim, bias=True)

        #self.init_h_sentence_dec = nn.Linear(encoder_dim, hidden_dim)  # linear layer to find initial hidden state of LSTMCell
        #self.init_c_sentence_dec = nn.Linear(encoder_dim, hidden_dim)  # linear layer to find initial cell state of LSTMCell
        #self.init_h_word_dec = nn.Linear(hidden_dim, hidden_dim)  # linear layer to find initial hidden state of LSTMCell
        #self.init_c_word_dec = nn.Linear(hidden_dim, hidden_dim)  # linear layer to find initial cell state of LSTMCell
        
        self.topic_vector = nn.Linear(hidden_dim, embed_dim)

        self.stop_h_1 = nn.Linear(hidden_dim, hidden_dim)
        self.stop_h = nn.Linear(hidden_dim, hidden_dim)

        self.stop = nn.Linear(hidden_dim, 1)

        #self.sentence_decoder_fc_sizes = [
        #    self.embed_dim,  # topic
        #    1                 # stop
        #]

        #self.sentence_decoder_fc = nn.Linear(self.hidden_dim, sum(self.sentence_decoder_fc_sizes))

        self.sigmoid = nn.Sigmoid()
        self.relu = nn.ReLU()
        self.tanh = nn.Tanh()

        #self.fc = nn.Linear(decoder_dim, embed_dim)  # linear layer to generate continuous outputs
        #self.init_weights()  # initialize some layers with the uniform distribution

    def init_weights(self):
        """
        Initializes some parameters with values from the uniform distribution, for easier convergence.
        """
        self.embedding.weight.data.uniform_(-0.1, 0.1)
        self.fc.bias.data.fill_(0)
        self.fc.weight.data.uniform_(-0.1, 0.1)
        #self.sentence_decoder_fc.weight.data.uniform_(-0.1, 0.1)
        #self.sentence_decoder_fc.bias.data.fill_(0)
        self.context_vector_fc.weight.data.uniform_(-0.1, 0.1)
        self.context_vector_fc.bias.data.fill_(0)
        self.resize_encoder_features.weight.data.uniform_(-0.1, 0.1)
        self.resize_encoder_features.bias.data.fill_(0)
        self.context_vector_W.weight.data.uniform_(-0.1, 0.1)
        self.context_vector_W.bias.data.fill_(0)
        self.context_vector_W_h_t.weight.data.uniform_(-0.1, 0.1)
        self.context_vector_W_h_t.bias.data.fill_(0)
        self.topic_vector.weight.data.uniform_(-0.1, 0.1)
        self.topic_vector.bias.data.fill_(0)
        self.stop_h_1.weight.data.uniform_(-0.1, 0.1)
        self.stop_h_1.bias.data.fill_(0)
        self.stop_h.weight.data.uniform_(-0.1, 0.1)
        self.stop_h.bias.data.fill_(0)
        self.stop.weight.data.uniform_(-0.1, 0.1)
        self.stop.bias.data.fill_(0)









    def load_pretrained_embeddings(self, embeddings):
        """
        Loads embedding layer with pre-trained embeddings.
        :param embeddings: pre-trained embeddings
        """
        self.embedding.weight = nn.Parameter(embeddings)

    def fine_tune_embeddings(self, fine_tune=False):
        """
        Allow fine-tuning of embedding layer? (Only makes sense to not-allow if using pre-trained embeddings).
        :param fine_tune: Allow?
        """
        for p in self.embedding.parameters():
            p.requires_grad = fine_tune

    def init_sent_hidden_state(self, batch_size):
        """
        Creates the initial hidden and cell states for the decoder's LSTM based on the encoded images.
        :param encoder_out: encoded images, a tensor of dimension (batch_size, num_pixels, encoder_dim)
        :return: hidden state, cell state
        """
        h_sent = torch.zeros(batch_size, self.hidden_dim, requires_grad = True).to(device)  # (batch_size, decoder_dim)
        c_sent = torch.zeros(batch_size, self.hidden_dim, requires_grad = True).to(device)
        return h_sent, c_sent


    def init_word_hidden_state(self, batch_size):
        """
        Creates the initial hidden and cell states for the decoder's LSTM based on the encoded images.
        :param encoder_out: encoded images, a tensor of dimension (batch_size, num_pixels, encoder_dim)
        :return: hidden state, cell state
        """
        h_word = torch.zeros(batch_size, self.hidden_dim, requires_grad = True).to(device)  # (batch_size, decoder_dim)
        c_word = torch.zeros(batch_size, self.hidden_dim, requires_grad = True).to(device)
        return h_word, c_word



    def set_teacher_forcing_usage(self, value):
        self.use_tf_as_input = value

    def set_scheduled_sampling_usage(self, value):
        self.use_scheduled_sampling = value

    def set_scheduled_sampling_prob(self, value):
        self.schedule_sampling_prob = value

    def should_use_prev_output():
        return random.random() < self.scheduled_sampling_prob

    @abstractmethod
    def forward(self, encoder_out, encoded_captions, caption_lengths):
        pass
