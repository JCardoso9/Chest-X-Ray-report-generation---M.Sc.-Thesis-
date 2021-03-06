
import sys
sys.path.append('../Utils/')
sys.path.append('../TestMethods/')

from setupEnvironment import *
from argParser import *
from TrainingEnvironment import *
from generalUtilities import *
from train import *
from beam_caption import *

import torch
import torch.backends.cudnn as cudnn

from datetime import datetime

from nlgeval import NLGEval


BEAM_SIZE = 4


def main():

    print("Starting training process MIMIC")

    nlgeval = NLGEval(metrics_to_omit=['SkipThoughtCS', 'GreedyMatchingScore', 'VectorExtremaCosineSimilarity', 'EmbeddingAverageCosineSimilarity'])

    argParser = get_args()

    if not os.path.isdir('../Experiments/' + argParser.model_name):
        os.mkdir('../Experiments/' + argParser.model_name)


    print(argParser)

    modelInfo = None
    classifierInfo = None

    if (argParser.checkpoint is not None):
        modelInfo = torch.load(argParser.checkpoint)

    if (argParser.use_classifier_encoder) and modelInfo is None:
        classifierInfo = torch.load(argParser.classifier_checkpoint)

    if not os.path.isdir('../Experiments/' + argParser.model_name):
        os.mkdir('../Experiments/' + argParser.model_name)

    trainingEnvironment = TrainingEnvironment(argParser)

    encoder, decoder = setupEncoderDecoder(argParser, modelInfo, classifierInfo)

    print("Use SS",decoder.use_scheduled_sampling)
    print("Use mogrifier",decoder.use_mogrifier)
    print("Use tf", decoder.use_tf_as_input)
    print("Initital SS prob:", decoder.scheduled_sampling_prob)
    print("dropout prob", decoder.dropout)


    encoder_optimizer, decoder_optimizer = setupOptimizers(encoder, decoder, argParser, modelInfo)

    decoder_scheduler, encoder_scheduler = setupSchedulers(encoder_optimizer, decoder_optimizer, argParser)

    criterion = setupCriterion(argParser.loss)

    trainLoader, valLoader = setupDataLoaders(argParser)

    # Load word <-> embeddings matrix index correspondence dictionaries
    idx2word, word2idx = loadWordIndexDicts(argParser)

    scheduled_sampling_prob = decoder.scheduled_sampling_prob

    cudnn.benchmark = True  # set to true only if inputs to model are fixed size; otherwise lot of computational overhead

    for epoch in range(trainingEnvironment.start_epoch, trainingEnvironment.epochs):

        if epoch > 1 and argParser.use_scheduled_sampling and epoch % argParser.scheduled_sampling_decay_epochs == 0:
            scheduled_sampling_prob += argParser.rate_change_scheduled_sampling_prob
            #decoder.set_scheduled_sampling_prob(scheduled_sampling_prob)
            decoder.scheduled_sampling_prob = scheduled_sampling_prob
            print("increased scheduled sampling prob to: ", decoder.scheduled_sampling_prob)
            print("Saved SS",scheduled_sampling_prob)

        # Decay learning rate if there is no improvement for "decay_LR_epoch_threshold" consecutive epochs,
        #  and terminate training after minimum LR has been achieved and  "early_stop_epoch_threshold" epochs without improvement
        if trainingEnvironment.epochs_since_improvement == argParser.early_stop_epoch_threshold:
            break

        # One epoch's training
        train(argParser,train_loader=trainLoader,
              encoder=encoder,
              decoder=decoder,
              criterion=criterion,
              encoder_optimizer=encoder_optimizer,
              decoder_optimizer=decoder_optimizer,
              epoch=epoch)

        # One epoch's validation
        #references, hypotheses = evaluate(argParser, 4, encoder, decoder, valLoader, word2idx, idx2word)
        references, hypotheses = evaluate_beam(argParser, BEAM_SIZE, encoder, decoder, valLoader, word2idx, idx2word)


        encoder_scheduler.step()
        decoder_scheduler.step()

        # nlgeval = NLGEval()
        metrics_dict = nlgeval.compute_metrics(references, hypotheses)

        print("Metrics: " , metrics_dict)
        with open('../Experiments/' + argParser.model_name + "/metrics.txt", "a+") as file:
            file.write("Epoch " + str(epoch) + " results:\n")
            for metric in metrics_dict:
                file.write(metric + ":" + str(metrics_dict[metric]) + "\n")
            file.write("------------------------------------------\n")

        recent_bleu4 = metrics_dict['CIDEr']

        # Check if there was an improvement
        is_best = recent_bleu4 > trainingEnvironment.best_bleu4

        trainingEnvironment.best_bleu4 = max(recent_bleu4, trainingEnvironment.best_bleu4)

        print("Best BLEU: ", trainingEnvironment.best_bleu4)
        if not is_best:
            trainingEnvironment.epochs_since_improvement += 1
            print("\nEpochs since last improvement: %d\n" % (trainingEnvironment.epochs_since_improvement,))
        else:
            trainingEnvironment.epochs_since_improvement = 0

        # Save checkpoint
        save_checkpoint(argParser.model_name, epoch, trainingEnvironment.epochs_since_improvement, encoder.state_dict(), decoder.state_dict(), encoder_optimizer.state_dict(),
                        decoder_optimizer.state_dict(), recent_bleu4, is_best, metrics_dict, trainingEnvironment.best_loss)





if __name__ == "__main__":
    main()


