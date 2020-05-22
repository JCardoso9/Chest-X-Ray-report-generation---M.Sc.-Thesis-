import torch
from torch.utils.data import Dataset
import json
import os
from PIL import Image
import re
import sys
import pandas as pd
sys.path.append('../Utils/')


from generalUtilities import *


class HierarchicalXRayDataset(Dataset):
    """MIMIC xray dataset."""


    def __init__(self,word2idx_path,   encodedCaptionsJsonFile, captionsLengthsFile, imgsDir, transform=None, maxSize = 372):
        """
        Args:
            json_file (string): Path to the json file with captions.
            root_dir (string): Directory with all the images.
            transform (callable, optional): Optional transform to be applied
                on a sample.
        """

        with open(word2idx_path) as json_file:
            self.word2idx = json.load(json_file)

        with open(encodedCaptionsJsonFile) as json_file:
            self.encodedCaptions = json.load(json_file)

        with open(captionsLengthsFile) as json_file:
            self.encodedCaptionsLength = json.load(json_file)

        #self.labels = pd.read_csv(labels_csv_path, index_col = 0)

        self.imgsDir = imgsDir
        self.transform = transform
        self.imgPaths = getFilesInDirectory(imgsDir)
        self.maxSize = maxSize
        self.vocab_size = len(self.word2idx.keys())

    def __len__(self):
        return len(self.encodedCaptions)

    def __getitem__(self, idx):

        imgID = self.imgPaths[idx]
        study = re.findall(r"s\d{8}", imgID)[0][1:]

        image = Image.open(imgID)

        encodedCaptionLength = 0
        encodedCaption = []

        # Start of caption token
        encodedCaptionLength += 1
        encodedCaption.append(self.word2idx['<sos>'])

        # Caption
        encodedCaptionLength += self.encodedCaptionsLength[study]
        encodedCaption = self.encodeCaption(self.encodedCaptions[study], encodedCaption)

        # End of caption token
        encodedCaptionLength += 1
        encodedCaption.append(self.word2idx['<eoc>'])


        sentences = self.getSentences(encodedCaption)

        print(encodedCaption)
        print(sentences)

        # Pad captions until all have max_size
        encodedCaption = self.padCaption(torch.LongTensor(encodedCaption), self.maxSize, encodedCaptionLength)

        #labels =  torch.tensor(self.labels.loc[int(study)].values[1:], dtype=torch.long)


        if self.transform:
            image = self.transform(image)

        return image,  torch.LongTensor(encodedCaption), encodedCaptionLength, sentences


    # Transform caption comprised of list of words into
    # list of ints according to the word -> index hash table
    def encodeCaption(self, caption, encodedCaption):
        for word in caption:
            if word in self.word2idx.keys():
                encodedCaption.append(self.word2idx[word])
            else:
                encodedCaption.append(self.word2idx['<unk>'])
        return encodedCaption

    # Pad caption to max Size
    def padCaption(self, caption, maxSize, encodedCaptionLength):
      nrOfPads = maxSize - encodedCaptionLength
      padIdx = self.word2idx['<pad>']

      padSequence = torch.full([nrOfPads], padIdx,dtype =torch.long)

      return torch.cat((caption, padSequence), 0)


    def getSentences(self,caption):
        size = len(caption) 
        idx_list = [idx + 1 for idx, val in
            enumerate(caption) if val == self.word2idx['.']] 
  
  
        res = [caption[i: j] for i, j in
            zip([0] + idx_list, idx_list + 
            ([size] if idx_list[-1] != size else []))]
        res[-2].extend(res[-1])
        res = res[:-1]
        return res
