import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from scipy import stats
import math
import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.utils.data as Data
import torch.nn.functional as F
import time
import matplotlib.pyplot as plt
from distance import *
from tqdm import tqdm
from sklearn.metrics import accuracy_score, precision_score, f1_score, recall_score, roc_auc_score, r2_score
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
plt.rcParams['axes.labelsize'] = 20
plt.rcParams['xtick.labelsize'] = 20
plt.rcParams['ytick.labelsize'] = 20

def feature_load(filename = 'm1912.csv'):
    dt_credit = pd.read_csv(filename,index_col = 0)
    dt_x = dt_credit.iloc[:,2:].fillna(0).to_numpy()
    dt_y = dt_credit.iloc[:,1].replace(['0+','30+','60+','90+','120+'],0)
    dt_y = dt_y.replace(['payoff'],1).to_numpy()
    scaler_input = MinMaxScaler(feature_range=(0, 1))
    x_trans = scaler_input.fit_transform(dt_x)
    return x_trans, dt_y

def feature_load_tgt_unbalanced(filename, frac):
    dt_credit = pd.read_csv(filename,index_col = 0)
    dt_x = dt_credit.iloc[:,2:].fillna(0).to_numpy()
    dt_y = dt_credit.iloc[:,1].replace(['0+','30+','60+','90+','120+'],0)
    dt_y = dt_y.replace(['payoff'],1).to_numpy()
    scaler_input = MinMaxScaler(feature_range=(0, 1))
    x_trans = scaler_input.fit_transform(dt_x)
    idx_1 = np.where(dt_y==1)[0]
    idx_0 = np.where(dt_y==0)[0]
    idx_0_extracted = np.random.choice(len(idx_0), size=int(frac*len(idx_0)), replace=False)
    combine = np.concatenate((idx_1, idx_0_extracted))
    return x_trans[combine, :], dt_y[combine]
class net_MLP(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim, drop_rate=0.1):
        super(net_MLP, self).__init__()
        self.layer1 = nn.Sequential(nn.BatchNorm1d(input_dim,momentum=0.5),
                                   nn.Linear(input_dim, hidden_dim),
                                   nn.ReLU(),
                                   nn.BatchNorm1d(hidden_dim,momentum=0.5),
                                   nn.Linear(hidden_dim, hidden_dim // 2),
                                   nn.ReLU())

        self.layer2 = nn.Sequential(nn.BatchNorm1d(hidden_dim // 2,momentum=0.5),
                                   nn.Tanh(),
                                   nn.Linear(hidden_dim // 2,output_dim))
    def forward(self, x):
        x = self.layer1(x)
        x = self.layer2(x)
        return x
    def forward_ft(self,x,y):
        x_f = self.layer1(x)
        y_f = self.layer1(y)
        return x_f,y_f
    def predict(self, y):
        y = self.layer1(y)
        y = self.layer2(y)
        return y
class net_DAN(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim, drop_rate=0.1, method='DAN'):
        super(net_DAN, self).__init__()
        self.method = method
        self.layer1 = nn.Sequential(nn.BatchNorm1d(input_dim), nn.Linear(input_dim, hidden_dim), nn.ReLU())
        self.layer2 = nn.Sequential(nn.BatchNorm1d(hidden_dim), nn.Linear(hidden_dim, hidden_dim // 2), nn.ReLU())
        self.layer3 = nn.Sequential(nn.BatchNorm1d(hidden_dim // 2), nn.Linear(hidden_dim // 2, hidden_dim // 4), nn.ReLU())
        self.layer4 = nn.Sequential(nn.BatchNorm1d(hidden_dim // 4), nn.Linear(hidden_dim // 4, output_dim))
    def forward(self, x, y):
        x,y = self.layer1(x), self.layer1(y)
        x,y = self.layer2(x), self.layer2(y)
        x,y = self.layer3(x), self.layer3(y)
        if self.method == 'DAN':
            total_div = MMD(x, y)
        elif self.method == 'CORAL':
            total_div = self.CORAL(x,y)
        x = self.layer4(x)
        return total_div, x
    def predict(self, y):
        y = self.layer1(y)
        y = self.layer2(y)
        y = self.layer3(y)
        y = self.layer4(y)
        return y
    def CORAL(self, source, target):
        d = source.data.shape[1]
        ns, nt = source.data.shape[0], target.data.shape[0]
        # source covariance
        xm = torch.mean(source, 0, keepdim=True) - source
        xc = xm.t() @ xm / (ns - 1)
        # target covariance
        xmt = torch.mean(target, 0, keepdim=True) - target
        xct = xmt.t() @ xmt / (nt - 1)
        # frobenius norm between source and target
        loss = torch.mul((xc - xct), (xc - xct))
        loss = torch.sum(loss) / (4*d*d)
        return loss
    def forward_ft(self,x,y):
        x_f = self.layer1(x)
        y_f = self.layer1(y)
        return x_f,y_f
class net_CDAN(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim, drop_rate=0.1):
        super(net_CDAN, self).__init__()
        self.layer1 = nn.Sequential(nn.BatchNorm1d(input_dim), nn.Linear(input_dim, hidden_dim), nn.ReLU(),
                                    nn.BatchNorm1d(hidden_dim), nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
                                    nn.BatchNorm1d(hidden_dim), nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
                                    nn.BatchNorm1d(hidden_dim), nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
                                    nn.BatchNorm1d(hidden_dim), nn.Linear(hidden_dim, hidden_dim // 2), nn.ReLU(),
                                    nn.BatchNorm1d(hidden_dim // 2), nn.Linear(hidden_dim // 2, hidden_dim // 16))
        self.layer2 = nn.Sequential(nn.BatchNorm1d(hidden_dim // 16), nn.Linear(hidden_dim // 16, output_dim))


    def forward(self, x, y):
        x, y = self.layer1(x), self.layer1(y)
        marginal_div = self.marginal_div(x, y)
        copula_distance = self.copula_distance(x, y)
        x = self.layer2(x)
        return marginal_div, copula_distance, x

    def predict(self, y):
        y = self.layer1(y)
        y = self.layer2(y)
        return y

    def marginal_div(self, X, Y, loss_metric='MMD'):
        if loss_metric == 'MMD':
            marginal_loss = MD_MMD(X, Y)
        else:
            marginal_loss = 0
        return marginal_loss

    def copula_distance(self, X, Y, loss_metric='KL'):
        if loss_metric == 'Frobenius':
            copula_loss = CD_Frobenius(X, Y)
        elif loss_metric == 'KL':
            copula_loss = CD_KL(X, Y)
        return copula_loss
    def forward_ft(self,x,y):
        x_f = self.layer1(x)
        y_f = self.layer1(y)
        return x_f,y_f
    
def train(mod, learning_rate, src_x, src_y, tgt_x, tgt_y):
    if mod['model']=='MLP':
        model = net_MLP(input_dim = mod['input'], hidden_dim = mod['hidden'], output_dim = mod['output']).to(device)
    elif mod['model']=='DAN':
        model = net_DAN(input_dim = mod['input'], hidden_dim = mod['hidden'], output_dim = mod['output']).to(device)
    elif mod['model'] == 'CORAL':
        model = net_DAN(input_dim = mod['input'], hidden_dim = mod['hidden'], output_dim = mod['output'], method='CORAL').to(device)
    elif mod['model']=='CDAN':
        model = net_CDAN(input_dim = mod['input'], hidden_dim = mod['hidden'], output_dim = mod['output']).to(device)

    src_dataset = Data.TensorDataset(torch.tensor(mod['src'][0]).float().to(device),torch.tensor(mod['src'][1]).long().to(device))
    src_loader = Data.DataLoader(src_dataset,batch_size = mod['batch_size'],shuffle=True,num_workers=0,drop_last=True)
    tgt_dataset = Data.TensorDataset(torch.tensor(mod['tgt'][0]).float().to(device),torch.tensor(mod['tgt'][1]).long().to(device))
    tgt_loader = Data.DataLoader(tgt_dataset,batch_size = mod['batch_size'],shuffle=True,num_workers=0,drop_last=True)

    loss_func = torch.nn.CrossEntropyLoss()
    log_interval = len(tgt_loader)
    rslt = {'l_src':[],'domain_div':[], 'total_div':[], 'copula_distance':[],'roc':[],'time':[]}
    src_iter = iter(src_loader)
    tgt_iter = iter(tgt_loader)
    roc = 0
    list_xf, list_yf, list_loss_src,list_domain_div,list_copula_distance, list_total_div =[],[],[],[],[],[]
    time_start = time.time()
    count = 0
    iterator = tqdm(range(1, mod['iteration']+1))
    for i in iterator:
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        try:
            src_data, src_label = src_iter.next()
        except Exception as err:
            src_iter=iter(src_loader)
            src_data, src_label = src_iter.next()
        try:
            tgt_data, tgt_label = tgt_iter.next()
        except Exception as err:
            tgt_iter=iter(tgt_loader)
            tgt_data, tgt_label = tgt_iter.next()

        optimizer.zero_grad()
        if mod['model'] == 'MLP':
            src_out = model(src_data)
            loss = loss_func(src_out, src_label)
        elif mod['model'] == 'DAN' or mod['model'] == 'CORAL':
            total_div, src_out = model(src_data, tgt_data)
            loss = loss_func(src_out, src_label) + mod['trade_off1'] * total_div
            list_total_div.append(total_div.cpu().data.numpy())
        elif mod['model'] == 'CDAN':
            marginal_div, copula_distance, src_out = model(src_data, tgt_data)
            loss = loss_func(src_out, src_label) + mod['trade_off1'] * marginal_div + mod[
                'trade_off2'] * copula_distance
            list_domain_div.append(marginal_div.cpu().data.numpy())
            list_copula_distance.append(copula_distance.cpu().data.numpy())
        list_loss_src.append(loss.cpu().data.numpy())
        loss.backward()
        optimizer.step()
        model.eval()
        x_f, y_f = model.forward_ft(src_data,tgt_data)
        list_xf.append(x_f.cpu().data.numpy())
        list_yf.append(y_f.cpu().data.numpy())
        if i % log_interval == 0:
            rslt['l_src'].append(np.average(list_loss_src))
            if list_domain_div:
                rslt['domain_div'].append(np.average(list_domain_div))
            else:
                rslt['domain_div'].append(0)
            if list_total_div:
                rslt['total_div'].append(np.average(list_total_div))
            else:
                rslt['total_div'].append(0)
            if list_copula_distance:
                rslt['copula_distance'].append(np.average(list_copula_distance))
            else:
                rslt['copula_distance'].append(0)
            print('Train iter: {} [({:.0f}%)]\tLoss: {:.6f}'.format(i, 100. * i / mod['iteration'],
                                                                    np.average(list_loss_src)))
            list_loss_src,list_domain_div,list_total_div,list_copula_distance = [],[],[],[]
            model.eval()
            tgt_out = model.predict(torch.tensor(tgt_x).float().to(device))
            tgt_loss = loss_func(tgt_out, torch.tensor(tgt_y).long().to(device))
            tgt_pred = torch.max(F.softmax(tgt_out,dim=1), 1)[1]
            tgt_pred_y = tgt_pred.cpu().data.numpy().squeeze()
            roc_update = roc_auc_score(tgt_y, tgt_pred_y)
            if roc_update > roc:
                roc = roc_update
            else:
                count += 1
            print('\n Target loss: {:.4f}, ROC: {}\n'.format(
                tgt_loss, roc))
            if count >= mod['patience']:
                iterator.close()
                print("Training stops at {}-th loop with best roc {}".format(i, roc))
                break
        time_end = time.time()
    rslt['roc'].append(roc)
    rslt['time'].append(time_end-time_start)
    return rslt, list_xf, list_yf, log_interval