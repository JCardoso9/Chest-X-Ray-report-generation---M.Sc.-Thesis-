import sys
sys.path.append('../Utils/')

from generalUtilities import *
from continuousModelUtilities import *

import torch
from torch.nn.utils.rnn import pack_padded_sequence
import torch.nn as nn
import time

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
DISABLE_TEACHER_FORCING = 0

def test(argParser,  testLoader, encoder, decoder, criterion, idx2word, embeddings):
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
    decoder.set_teacher_forcing_usage(DISABLE_TEACHER_FORCING)
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
            decoder_output, caps_sorted, decode_lengths, alphas, sort_ind = decoder(imgs, caps, caplens)

            # Since we decoded starting with <start>, the targets are all words after <start>, up to <end>
            targets = caps_sorted[:, 1:]

            # Remove timesteps that we didn't decode at, or are pads
            # pack_padded_sequence is an easy trick to do this
            decoder_output_copy = decoder_output.clone()

            # Calculate loss
            if argParser.model == 'Continuous':
                targets = decoder.embedding(targets)
                if argParser.normalizeEmb:
                    targets = nn.functional.normalize(targets, p=2, dim=1)
                    preds = nn.functional.normalize(decoder_output, p=2, dim=1)
                loss = criterion(preds, targets, decode_lengths)

            elif argParser.model == 'Softmax':
                decoder_output = pack_padded_sequence(decoder_output, decode_lengths, batch_first=True)
                targets = pack_padded_sequence(targets, decode_lengths, batch_first=True)
                loss = criterion(decoder_output.data, targets.data)


            # Add doubly stochastic attention regularization
            loss += argParser.alpha_c * ((1. - alphas.sum(dim=1)) ** 2).mean()

            # Keep track of metrics
            losses.update(loss.item(), sum(decode_lengths))
            #top5 = accuracy(scores, targets, 5)
            #top5accs.update(top5, sum(decode_lengths))
            batch_time.update(time.time() - start)

            start = time.time()

            if i % argParser.print_freq == 0:
                print('Validation: [{0}/{1}]\t'
                      'Batch Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'.format(i, len(testLoader), batch_time=batch_time,
                                                                                loss=losses))


            # Store references (true captions), and hypothesis (prediction) for each image
            # references = [[ref1, ref2, ...]], hypotheses = [hyp1, hyp2, ...]

            # References
            temp_refs = []
            caps_sortedList = caps_sorted[:, 1:].tolist()
            for j,refCaption in enumerate(caps_sortedList):
              temp_refs.append(refCaption[:decode_lengths[j]])

            for caption in temp_refs:
              references[0].append(decodeCaption(caption, idx2word))


             # Hypotheses
            if argParser.model == 'Continuous':
              batch_hypotheses = generatePredictedCaptions(decoder_output_copy, decode_lengths, embeddings, idx2word)
              hypotheses.extend(batch_hypotheses)


            elif argParser.model == 'Softmax':
              _, preds = torch.max(decoder_output_copy, dim=2)
              preds = preds.tolist()
              temp_preds = list()
              for j, p in enumerate(preds):
                temp_preds.append(preds[j][:decode_lengths[j]])  # remove pads
              preds = temp_preds

              for caption in preds:
                hypotheses.append(decodeCaption(caption, idx2word))


#            print("REFS:", references[0])
#            print("HIPS: ", hypotheses)
 #           break
            assert len(references[0]) == len(hypotheses)


    path = '../Experiments/' +  argParser.model_name + '/testLoss.txt'
    writeLossToFile(losses.avg, path)

    return references, hypotheses
