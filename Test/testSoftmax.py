import argparse, json
from utils import *
from encoder import Encoder
from Attention import *
from DecoderWAttention import *
from XRayDataset import *

import torch
import os
import numpy as np

from PIL import Image
import re
import torch.nn as nn
import pickle
import time
from datetime import datetime


import torch.nn as nn
import torch.optim as optim
from nltk.translate.bleu_score import corpus_bleu
import torch.backends.cudnn as cudnn
import torchvision
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, utils
from torch.autograd import Variable
from torch.nn.utils.rnn import pack_padded_sequence

from nlgeval import NLGEval


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Training parameters
start_epoch = 0
epochs = 20  # number of epochs to train for (if early stopping is not triggered)
epochs_since_improvement = 0  # keeps track of number of epochs since there's been an improvement in validation BLEU
batch_size = 16
workers = 1  # for data-loading; right now, only 1 works with h5py
encoder_lr = 1e-4  # learning rate for encoder if fine-tuning
decoder_lr = 4e-4  # learning rate for decoder
grad_clip = 5.  # clip gradients at an absolute value of
alpha_c = 1.  # regularization parameter for 'doubly stochastic attention', as in the paper
best_bleu4 = 0.  # BLEU-4 score right now
print_freq = 5  # print training/validation stats every __ batches
fine_tune_encoder = False  # fine-tune encoder?
checkpoint = None  # path to checkpoint, None if none


def test(idx2word, testLoader, encoder, decoder, criterion):
    """
    Performs testing for the pretrained model
    :param word_map: dictionary with word -> embedding correspondence
    :param embeddings: Embeddings matrix 
    :param idx2word: dictionary with index -> word correspondence.
    :param testLoader: loader for test data
    :param encoder: encoder model
    :param decoder: decoder model
    :param criterion: loss layer
    :return: BLEU-4 score
    """
    decoder.eval()  # eval mode (no dropout or batchnorm)
    if encoder is not None:
        encoder.eval()

    batch_time = AverageMeter()
    losses = AverageMeter()
    #top5accs = AverageMeter()

    start = time.time()

    references = list()  # references (true captions) for calculating BLEU-4 score
    references.append([])
    hypotheses = list()  # hypotheses (predictions)


    # explicitly disable gradient calculation to avoid CUDA memory error
    # solves the issue #57
    with torch.no_grad():
        # Batches
        for i, (imgs, caps, caplens) in enumerate(testLoader):

            # Move to device, if available
            imgs = imgs.to(device)
            caps = caps.to(device)
            caplens = caplens.to(device)

            # Forward prop.
            if encoder is not None:
                imgs = encoder(imgs)
            scores, caps_sorted, decode_lengths, alphas, sort_ind = decoder(imgs, caps, caplens)

            # Since we decoded starting with <start>, the targets are all words after <start>, up to <end>
            targets = caps_sorted[:, 1:]

            # Remove timesteps that we didn't decode at, or are pads
            # pack_padded_sequence is an easy trick to do this
            scores_copy = scores.clone()
            scores = pack_padded_sequence(scores, decode_lengths, batch_first=True)
            targets = pack_padded_sequence(targets, decode_lengths, batch_first=True)

            # Calculate loss
            loss = criterion(scores.data, targets.data)

            # Add doubly stochastic attention regularization
            loss += alpha_c * ((1. - alphas.sum(dim=1)) ** 2).mean()

            # Keep track of metrics
            losses.update(loss.item(), sum(decode_lengths))
            #top5 = accuracy(scores, targets, 5)
            #top5accs.update(top5, sum(decode_lengths))
            batch_time.update(time.time() - start)

            start = time.time()

            if i % print_freq == 0:
                print('Validation: [{0}/{1}]\t'
                      'Batch Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'.format(i, len(testLoader), batch_time=batch_time,
                                                                                loss=losses))
                

            # Store references (true captions), and hypothesis (prediction) for each image
            # references = [[ref1, ref2, ...]], hypotheses = [hyp1, hyp2, ...]
        

            temp_refs = []
            caps_sortedList = caps_sorted[:, 1:].tolist()
            for j,refCaption in enumerate(caps_sortedList):
              temp_refs.append(refCaption[:decode_lengths[j]]) 

            for caption in temp_refs:
              references[0].append(decodeCaption(caption, idx2word))

            # print("Caps sorted: ", caps_sorted.shape)
            # print("References:", len(references))
            # print("Full references: ", references)

                      

            # Hypotheses
            _, preds = torch.max(scores_copy, dim=2)
            preds = preds.tolist()
            temp_preds = list()
            for j, p in enumerate(preds):
                temp_preds.append(preds[j][:decode_lengths[j]])  # remove pads
            preds = temp_preds

            for caption in preds:
              hypotheses.append(decodeCaption(caption, idx2word))
                    

            assert len(references[0]) == len(hypotheses)


    now = datetime.now()
    day_string = now.strftime("%d_%m_%Y")
    path = 'testLoss' + day_string
    writeLossToFile(losses.avg, path)

    return references, hypotheses



def main(modelInfoPath):
  """
    Performs testing on the trained model.
    :param modelInfoPath: Path to the model saved during the training process
  """
  device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

  # Load dictionary with index -> word correspondence
  with open('/home/jcardoso/MIMIC/idx2word.json') as fp:
        idx2word = json.load(fp)

  # Create NlG metrics evaluator
  nlgeval = NLGEval(metrics_to_omit=['SkipThoughtCS', 'GreedyMatchingScore', 'VectorExtremaCosineSimilarity', 'EmbeddingAverageCosineSimilarity'])

  #Load embeddings 
  word_map, embeddings, vocab_size, embed_dim = loadEmbeddingsFromDisk('/home/jcardoso/MIMIC/embeddingsMIMIC.pkl')

  attention_dim = 512  # dimension of attention linear layers
  decoder_dim = 512  # dimension of decoder RNN

  decoder = DecoderWithAttention(attention_dim=attention_dim,
                                    embed_dim=embed_dim,
                                    decoder_dim=decoder_dim,
                                    vocab_size=vocab_size,
                                    dropout=0.5)

  decoder.load_pretrained_embeddings(embeddings)  
  encoder = Encoder()

  # Load trained model
  modelInfo = torch.load(modelInfoPath)
  decoder.load_state_dict(modelInfo['decoder'])
  encoder.load_state_dict(modelInfo['encoder'])

  # Move to GPU, if available
  decoder = decoder.to(device)
  encoder = encoder.to(device)

  criterion = nn.CrossEntropyLoss().to(device)

  transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
    ])

  # Create MIMIC test dataset loader
  testLoader = DataLoader(
      XRayDataset("/home/jcardoso/MIMIC/word2idx.json","/home/jcardoso/MIMIC/encodedTestCaptions.json",'/home/jcardoso/MIMIC/encodedTestCaptionsLengths.json','/home/jcardoso/MIMIC/Test', transform),
      batch_size=4, shuffle=True)
  
  references, hypotheses = test(idx2word, testLoader=testLoader,
                                encoder=encoder,
                                decoder=decoder,
                                criterion=criterion)
  
  metrics_dict = nlgeval.compute_metrics(references, hypotheses)

  with open(modelInfoPath + "_TestResults.txt", "w+") as file:
    for metric in metrics_dict:
      file.write(metric + ":" + str(metrics_dict[metric]) + "\n")

  
  
if __name__ == "__main__":
    main()

