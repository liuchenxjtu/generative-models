from __future__ import print_function
import argparse
import random
import torch
import torch.nn as nn
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import torch.optim as optim
import torch.utils.data
import torchvision.datasets as dset
import torchvision.transforms as transforms
import torchvision.utils as vutils
from torch.autograd import Variable
import os
from dataset import DatasetFromPandas
import models.dcgan as dcgan
import models.mlp as mlp
import pandas as pd
from sklearn import metrics
from sklearn.metrics import confusion_matrix

parser = argparse.ArgumentParser()
parser.add_argument('--pos_data', default='/storage03/user_data/liuchen01/creds/bank_combined_train', help='path to dataset')
parser.add_argument('--neg_data', default='/storage03/user_data/liuchen01/creds/bank_combined_noisy', help='path to dataset')
parser.add_argument('--test_data', default='/storage03/user_data/liuchen01/creds/bank_combined_test', help='path to dataset')
parser.add_argument('--test_label', default='/storage03/user_data/liuchen01/creds/test_labels.dat', help='path to dataset')
parser.add_argument('--workers', type=int, help='number of data loading workers', default=2)
parser.add_argument('--batchSize', type=int, default=128, help='input batch size')
parser.add_argument('--nSize', type=int, default=248, help='noise size')
parser.add_argument('--nz', type=int, default=148, help='size of the latent z vector')
parser.add_argument('--ngf', type=int, default=64)
parser.add_argument('--ndf', type=int, default=64)
parser.add_argument('--niter', type=int, default=25, help='number of epochs to train for')
parser.add_argument('--lrD', type=float, default=0.00005, help='learning rate for Critic, default=0.00005')
parser.add_argument('--lrG', type=float, default=0.00005, help='learning rate for Generator, default=0.00005')
parser.add_argument('--beta1', type=float, default=0.5, help='beta1 for adam. default=0.5')
parser.add_argument('--cuda'  , action='store_true',default=True, help='enables cuda')
parser.add_argument('--ngpu'  , type=int, default=1, help='number of GPUs to use')
parser.add_argument('--netG', default='', help="path to netG (to continue training)")
parser.add_argument('--netD', default='', help="path to netD (to continue training)")
parser.add_argument('--netP', default='samples/netD_epoch_24.pth', help="path to netP (to continue training)")
parser.add_argument('--clamp_lower', type=float, default=-0.02)
parser.add_argument('--clamp_upper', type=float, default=0.02)
parser.add_argument('--Diters', type=int, default=5, help='number of D iters per each G iter')
parser.add_argument('--noBN', action='store_true', help='use batchnorm or not (only for DCGAN)')
parser.add_argument('--mlp_G', action='store_true',default=True, help='use MLP for G')
parser.add_argument('--mlp_D', action='store_true', default=True,help='use MLP for D')
parser.add_argument('--n_extra_layers', type=int, default=0, help='Number of extra layers on gen and disc')
parser.add_argument('--experiment', default=None, help='Where to store samples and models')
parser.add_argument('--adam', action='store_true', help='Whether to use adam (default is rmsprop)')
opt, unknown = parser.parse_known_args()
print(opt)

if opt.experiment is None:
    opt.experiment = 'samples'
os.system('mkdir {0}'.format(opt.experiment))
opt.manualSeed = random.randint(1, 10000) # fix seed
print("Random Seed: ", opt.manualSeed)
random.seed(opt.manualSeed)
torch.manual_seed(opt.manualSeed)
cudnn.benchmark = True
if torch.cuda.is_available() and not opt.cuda:
    print("WARNING: You have a CUDA device, so you should probably run with --cuda")
pos_data = DatasetFromPandas(opt.pos_data)
neg_data = DatasetFromPandas(opt.neg_data)
dataloader = torch.utils.data.DataLoader(pos_data, batch_size=opt.batchSize,
                                         shuffle=True, num_workers=int(opt.workers))
neg_dataloader = torch.utils.data.DataLoader(neg_data, batch_size=opt.batchSize,
                                         shuffle=True, num_workers=int(opt.workers))
test = DatasetFromPandas(opt.test_data)
labels = list(pd.read_csv(opt.test_label,header=None)[0])
testdataloader = torch.utils.data.DataLoader(test, batch_size=len(test),
                                     shuffle=False, num_workers=int(opt.workers))
testdataiter = iter(testdataloader)
if opt.cuda:
    testv = Variable(testdataiter.next().cuda())
else:
    testv = Variable(testdataiter.next())
ngpu = int(opt.ngpu)
nSize = int(opt.nz)
nz = int(opt.nz)
nSize = int (opt.nSize)
ngf = int(opt.ngf)
ndf = int(opt.ndf)
n_extra_layers = int(opt.n_extra_layers)

# custom weights initialization called on netG and netD
def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        m.weight.data.normal_(0.0, 0.02)
    elif classname.find('BatchNorm') != -1:
        m.weight.data.normal_(1.0, 0.02)
        m.bias.data.fill_(0)

if opt.noBN:
    netG = dcgan.DCGAN_G_nobn(opt.imageSize, nz, nc, ngf, ngpu, n_extra_layers)
elif opt.mlp_G:
    netG = mlp.MLP_G(nSize, nz,  ngf, ngpu)
else:
    netG = dcgan.DCGAN_G(opt.imageSize, nz, nc, ngf, ngpu, n_extra_layers)

netG.apply(weights_init)
if opt.netG != '': # load checkpoint if needed
    netG.load_state_dict(torch.load(opt.netG))
print(netG)

if opt.mlp_D:
    netD = mlp.MLP_D(opt.nSize,  ndf, ngpu)
else:
    netD = dcgan.DCGAN_D(opt.imageSize, nz, nc, ndf, ngpu, n_extra_layers)
    netD.apply(weights_init)
if opt.netD != '':
    netD.load_state_dict(torch.load(opt.netD))
print(netD)

# if opt.netP != '': # load checkpoint if needed
#     netP.load_state_dict(torch.load(opt.netG))

input = torch.FloatTensor(opt.batchSize, opt.nSize)
noise = torch.FloatTensor(opt.batchSize, nz)
# fixed_noise = torch.FloatTensor(opt.batchSize, nz, 1, 1).normal_(0, 1)
one = torch.FloatTensor([1])
mone = one *-1

if opt.cuda:
    netD.cuda()
    netG.cuda()
    input = input.cuda()
    one, mone = one.cuda(), mone.cuda()
    noise = noise.cuda()

# setup optimizer
if opt.adam:
    optimizerD = optim.Adam(netD.parameters(), lr=opt.lrD, betas=(opt.beta1, 0.999))
    optimizerG = optim.Adam(netG.parameters(), lr=opt.lrG, betas=(opt.beta1, 0.999))
else:
    optimizerD = optim.RMSprop(netD.parameters(), lr = opt.lrD)
    optimizerG = optim.RMSprop(netG.parameters(), lr = opt.lrG)
gen_iterations = 0
for epoch in range(200):
    data_iter = iter(dataloader)
    neg_iter = iter(neg_dataloader)
    i = 0
    while i < len(dataloader):
        ############################
        # (1) Update D network
        ###########################
        for p in netD.parameters(): # reset requires_grad
            p.requires_grad = True # they are set to False below in netG update

        # train the discriminator Diters times
        if gen_iterations < 25 or gen_iterations % 500 == 0:
            Diters = 100
        else:
            Diters = opt.Diters
        j = 0
        while j < Diters and i < len(dataloader):
            j += 1
            # clamp parameters to a cube
            for p in netD.parameters():
                p.data.clamp_(opt.clamp_lower, opt.clamp_upper)
            data = data_iter.next()
            i += 1
            # train with real
            real_cpu = data
            netD.zero_grad()
            # batch_size = real_cpu.size(0)
            if opt.cuda:
                real_cpu = real_cpu.cuda()
            input.resize_as_(real_cpu).copy_(real_cpu)
            inputv = Variable(input)
            errD_real = netD(inputv)
            errD_real.backward(one)
            # train with fake
            try:
                noise = neg_iter.next()
#                 print (noise.size())
            except:
                neg_iter = iter(neg_dataloader)
                noise = neg_iter.next()
#             noise.resize_(opt.batchSize, nz).normal_(0, 1)
#             noise = torch.cat((noise,torch.FloatTensor(opt.batchSize, 100).normal_(0, 1)),1)
            if opt.cuda:
                noise = noise.cuda()
            noisev = Variable(noise, volatile = True) # totally freeze netG
            fake = Variable(netG(noisev).data)
#             inputv = fake
            errD_fake = netD(fake)
            print
            errD_fake.backward(mone)
            errD = errD_real - errD_fake
            optimizerD.step()

        ############################
        # (2) Update G network
        ###########################
        for p in netD.parameters():
            p.requires_grad = False # to avoid computation
        netG.zero_grad()
        # in case our last batch was the tail batch of the dataloader,
        # make sure we feed a full batch of noise
        try:
                noise = neg_iter.next()
        except:
                neg_iter = iter(neg_dataloader)
                noise = neg_iter.next()
#         noise.resize_(opt.batchSize, nz).normal_(0, 1)
#         noise = torch.cat((noise,torch.FloatTensor(opt.batchSize, 100).normal_(0, 1)),1)
        if opt.cuda:
                noise = noise.cuda()
        noisev = Variable(noise)
        fake1 = netG(noisev)
        errG = netD(fake1)

#         errG.backward(one)
        optimizerG.step()
        gen_iterations += 1

    print('[%d/%d][%d/%d][%d] Loss_D: %f Loss_G: %f Loss_D_real: %f Loss_D_fake %f'
        % (epoch, opt.niter, i, len(dataloader), gen_iterations,
        errD.data[0], errG.data[0], errD_real.data[0], errD_fake.data[0]))
    if epoch %5==0:
        torch.save(netD.state_dict(), '{0}/wgan_netD_epoch_{1}.pth'.format(opt.experiment, epoch))


#     netP = mlp.MLP_P(opt.nSize,  ndf, ngpu)
# #     netP.load_state_dict(torch.load('{0}/netD_epoch_{1}.pth'.format(opt.experiment, epoch)))
#
#     netP.load_state_dict(netD.state_dict())
#     if opt.cuda:
#         netP.cuda()
#     # pred_probs = (netP((inputv)).cpu().data.numpy())
    # print (max(pred_probs),min(pred_probs))
    # pred_probs = (netP((fake)).cpu().data.numpy())
    # print (max(pred_probs),min(pred_probs))
    #
    # pred_probs = (netP((fake1)).cpu().data.numpy())
    # print (max(pred_probs),min(pred_probs))
    # pred_probs = (netP((testv)).cpu().data.numpy())
    # print (max(pred_probs),min(pred_probs),len(pred_probs))
    # pred_probs = (netP(netG(testv)).cpu().data.numpy())
    # print (max(pred_probs),min(pred_probs),len(pred_probs))
    #
    # pred_probs = (pred_probs-min(pred_probs))/(max(pred_probs)-min(pred_probs))
    # for i in range(0,10,2):
    #     pred = [1 if j>i/10.0 else 0 for j in pred_probs ]
    #     print (confusion_matrix(labels,pred))
    #     print ("Accuracy, ",  metrics.accuracy_score(labels,pred))
