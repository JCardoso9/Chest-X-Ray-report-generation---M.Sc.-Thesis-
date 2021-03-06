import sys
sys.path.append('../../')

import torch
from torch import nn
import torchvision
import torch.nn.functional as F
from efficientnet_pytorch import EfficientNet



class ClassifyingEncoder(nn.Module):
    """
    Encoder.
    """

    def __init__(self, encoded_image_size=14, network_name='densenet121'):
        super(ClassifyingEncoder, self).__init__()
        self.enc_image_size = encoded_image_size
        self.network_name= network_name
        self.nr_classes = 28


        if self.network_name == 'densenet121':
            self.dim = 1024

            self.net = torchvision.models.densenet121(pretrained=True)
            self.batch_norm = list(list(self.net.children())[0])[-1]
            self.net = nn.Sequential(*list(list(self.net.children())[0])[:-1])
            self.classifier = nn.Linear(self.dim, self.nr_classes)

        elif self.network_name == "efficient_net":
            print("Classifier is efficient net")
            self.dim = 1280
            self.net = EfficientNet.from_pretrained('efficientnet-b3', num_classes=28)


        self.fine_tune()

    def forward(self, images):
        """
        Forward propagation.
        :param images: images, a tensor of dimensions (batch_size, 3, image_size, image_size)
        :return: encoded images
        """
        if self.network_name == "efficient_net":
            class_preds_logits = self.net(img)
            #with torch.no_grad():
                #img_features = self.net.extract_features(img)
            print("features shape", img_features.shape)

            return None, class_preds_logits


        img_features = self.net(images)
        norm_batch = self.batch_norm(img_features)
        out = F.relu(norm_batch, inplace=True)
        out = F.adaptive_avg_pool2d(out, (1, 1))
        out = torch.flatten(out, 1)
        class_preds_logits = self.classifier(out)

        img_features = img_features.permute(0, 2, 3, 1)
        #print("Out of encoder", img_features.shape)
        return img_features, class_preds_logits


        #out = self.net(images)  # (batch_size, 2048, image_size/32, image_size/32)
        #out = self.adaptive_pool(out)  # (batch_size, 2048, encoded_image_size, encoded_image_size)
        #out = out.permute(0, 2, 3, 1)  # (batch_size, encoded_image_size, encoded_image_size, 2048)
        #return out

    def fine_tune(self, fine_tune=True):
        """
        Allow or prevent the computation of gradients for convolutional blocks 2 through 4 of the encoder.
        :param fine_tune: Allow?
        """
        for p in self.net.parameters():
            p.requires_grad = False
        # If fine-tuning, only fine-tune convolutional blocks 2 through 4
        if self.network_name == 'densenet121':
            for c in list(self.net.children())[8:]:
                for p in c.parameters():
                    p.requires_grad = fine_tune
