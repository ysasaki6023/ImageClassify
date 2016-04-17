#!/usr/bin/env python
# -*- coding: utf-8 -*-
import cPickle as pickle
import argparse
import time
import glob,sys
import os,csv

import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
import chainer
from chainer import cuda
import chainer.links as L
import chainer.functions as F
from chainer import optimizers, Variable, FunctionSet
from chainer import serializers

# Set variables
dataFolder = "data"
inputPixels = 100
Train_Frac = 0.0003 # Frac will be used for the training
Test_Frac  = 0.0003 # Frac will be used for the training

# Read arg
parser = argparse.ArgumentParser(description='XXX')
parser.add_argument('--initmodel', '-m', default='',
                    help='Initialize the model from given file')
parser.add_argument('--resume', '-r', default='',
                    help='Resume the optimization from snapshot')
#parser.add_argument('--epoch', '-e', default=200, type=int,
#                    help='number of epochs to learn')
parser.add_argument('--unit', '-u', default=1000, type=int,
                    help='number of units')
parser.add_argument('--batchsize', '-b', type=int, default=100,
                    help='learning minibatch size')
args = parser.parse_args()

batchsize = args.batchsize
n_units = args.unit

print('# unit: {}'.format(args.unit))
print('# Minibatch-size: {}'.format(args.batchsize))
print('')

# define input samples
x_files = []
y_files = []

for fname in glob.glob(dataFolder+"/*/*.jpg"):
    #print fname
    _,y,x = fname.replace(".jpg","").split("/")
    x_files.append(fname)
    y_files.append(y)
 
y_uniq = list(set(y_files))
#y_data = np.zeros( (len(y_files), len(y_uniq) ) )
y_data = np.zeros( (len(y_files) ), dtype=np.int32 )
y_files= np.array(y_files,dtype="string")
x_files= np.array(x_files,dtype="string")
for i,s in enumerate(y_uniq):
    y_data[y_files == s] = i

# Prepare training data
Perm = np.random.permutation(len(y_data))
i_train,i_test,_ = np.split(Perm,[int(len(Perm)*(Train_Frac)),int(len(Perm)*(Train_Frac+Test_Frac))])

xp = np

class MLP(chainer.Chain):
    def __init__(self):
        super(MLP,self).__init__(
            l1=F.Linear(inputPixels*inputPixels*3, n_units),
            l2=F.Linear(n_units, n_units),
            l3=F.Linear(n_units, len(y_uniq)))
    def __call__(self, x):
        h1 = F.dropout(F.relu(self.l1(x )))
        h2 = F.dropout(F.relu(self.l2(h1)))
        y  = self.l3(h2)
        return y

class Classifier(chainer.Chain):
    def __init__(self,predictor):
        super(Classifier,self).__init__(predictor=predictor)

    def __call__(self, x, t):
        y = self.predictor(x)
        self.loss = F.softmax_cross_entropy(y,t)
        self.accuracy = F.accuracy(y,t)
        self.y = y
        return self.loss


# Setup optimizer
model     = Classifier(MLP())
model.epoch = 0

# Init/Resume
if args.resume:
    print('Load model state from', args.resume)
    with open(args.resume,"rb") as f:
        model = pickle.load(f)

optimizer = optimizers.Adam()
optimizer.setup(model)

def loadImages(fileNames):
    x_data = None
    for iFile,fName in enumerate(fileNames):
        img = Image.open( fName ).convert("RGB")
        size = img.size
        cropBox = (int( size[0]/2 - min(size)/2), int( size[1]/2 - min(size)/2),
                   int( size[0]/2 + min(size)/2), int( size[1]/2 + min(size)/2))
        img = img.crop(cropBox)
        img = img.resize((inputPixels,inputPixels))
        nimg = np.array(img)
        # plt.imshow(nimg)
        # plt.show()
        aimg = nimg.ravel() / 256.
        if iFile==0:
            x_data = np.zeros((len(fileNames),len(aimg)),dtype=np.float32)
        x_data[iFile,:] = aimg
    return x_data

def dumpFile(outFileName, dataIndex, oriClass, estClass, comment):
    with open(outFileName,"w") as f:
        writer = csv.writer(f,lineterminator='\n')
        header = ["index","originalClass","estimatedClass","flag"]
        writer.writerow(header)
        for line in zip(dataIndex,oriClass,estClass,comment):
            writer.writerow(line)

# Learning loop

while True:
    model.epoch += 1
    print 'epoch', model.epoch 

    # save
    save_dataIndex     = np.zeros(len(i_train)+len(i_test),dtype=np.int32)
    #save_fileName      = np.zeros(len(i_train)+len(i_test),dtype="string")
    save_oriClass      = np.zeros(len(i_train)+len(i_test),dtype=np.int32)
    save_estClass      = np.zeros(len(i_train)+len(i_test),dtype=np.int32)
    save_comment       = np.zeros(len(i_train)+len(i_test),dtype="string")
    save_Ntrain        = 0
    save_Ntest         = 0

    # training
    perm = np.random.permutation(len(i_train))
    sum_accuracy = 0
    sum_loss = 0
    sum_totl = 0
    time_load = 0.
    time_calc = 0.
    for i in range(0, len(i_train), batchsize):
        start = time.time()
        x = Variable(loadImages(x_files[i_train[perm[i:i + batchsize]]]))
        t = Variable(xp.asarray(y_data [i_train[perm[i:i + batchsize]]]))
        mid   = time.time()
        optimizer.zero_grads()
        loss = model(x,t)

        loss.backward()
        optimizer.update()

        end   = time.time()

        sum_loss     += float(cuda.to_cpu(loss.data)) * batchsize
        sum_accuracy += float(model.accuracy.data) * batchsize
        sum_totl     += batchsize
        time_load += mid - start
        time_calc += end - mid

        Nlen = len(i_train[perm[i:i + batchsize]])
        save_dataIndex[i:i+Nlen] = i_train[perm[i:i + batchsize]]
        #save_fileName [i:i+Nlen] = x_files[i_train[perm[i:i + batchsize]]]
        save_oriClass [i:i+Nlen] = y_data [i_train[perm[i:i + batchsize]]]
        save_estClass [i:i+Nlen] = np.argmax(model.y.data,axis=1)
        save_comment  [i:i+Nlen] = "t"
        save_Ntrain += Nlen
    train_loss = sum_loss     / sum_totl
    train_accu = sum_accuracy / sum_totl
    print 'train mean loss=%3.2e, accuracy = %d%%'%( train_loss, train_accu * 100.)

    # test
    perm = np.random.permutation(len(i_test))
    sum_loss = 0
    sum_totl = 0
    for i in range(0, len(i_test), batchsize):
        x = Variable(loadImages(x_files[i_test[perm[i:i + batchsize]]]),volatile="on")
        t = Variable(xp.asarray(y_data [i_test[perm[i:i + batchsize]]]),volatile="on")
        loss = model(x,t)

        sum_loss     += float(cuda.to_cpu(loss.data)) * batchsize
        sum_accuracy += float(model.accuracy.data) * batchsize
        sum_totl     += batchsize

        Nlen = len(i_test[perm[i:i + batchsize]])
        save_dataIndex[save_Ntrain+i:save_Ntrain+i+Nlen] = i_test[perm[i:i + batchsize]]
        #save_fileName [save_Ntrain+i:save_Ntrain+i+Nlen] = x_files[i_test[perm[i:i + batchsize]]]
        save_oriClass [save_Ntrain+i:save_Ntrain+i+Nlen] = y_data [i_test[perm[i:i + batchsize]]]
        save_estClass [save_Ntrain+i:save_Ntrain+i+Nlen] = np.argmax(model.y.data,axis=1)
        save_comment  [save_Ntrain+i:save_Ntrain+i+Nlen] = "e"
        save_Ntest += Nlen
    test_loss = sum_loss     / sum_totl
    test_accu = sum_accuracy / sum_totl
    print 'test  mean loss=%3.2e, accuracy = %d%%'%( test_loss, test_accu * 100.)

    # Save the model and the optimizer
    print 'saving files ...'
    dirName = "output/test"
    if not os.path.exists(dirName):
        os.makedirs(dirName)
    if model.epoch == 1:
        with open(os.path.join(dirName,"classIndex.csv"),"w") as f:
            writer = csv.writer(f,lineterminator='\n')
            for line in enumerate(y_uniq):
                writer.writerow(line)
        with open(os.path.join(dirName,"fileIndex.csv"),"w") as f:
            writer = csv.writer(f,lineterminator='\n')
            for i,line in enumerate(zip(y_data,y_files,x_files)):
                writer.writerow([i]+list(line))
        with open(os.path.join(dirName,"trainProgress.csv"),"wa") as f:
            writer = csv.writer(f,lineterminator='\n')
            writer.writerow([model.epoch,train_loss,train_accu,test_loss,test_accu])

    with open(os.path.join(dirName,"model.pickle"),"wb") as f:
        pickle.dump(model,f)
                
    dumpFile(os.path.join(dirName,"epoch_%d.csv"%model.epoch),
             save_dataIndex[:save_Ntrain+save_Ntest],
             save_oriClass[:save_Ntrain+save_Ntest],
             save_estClass[:save_Ntrain+save_Ntest],
             save_comment[:save_Ntrain+save_Ntest])

    print 'done' 

