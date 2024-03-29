import torch
import pandas as pd

Data = pd.read_csv('./data/dataset_iso_v1.csv')
device = 'cuda' if torch.cuda.is_available() else 'cpu'

chars = set()
for string in Data['SMILES']:
    chars.update(string)
train_data = Data[Data['SPLIT'] == 'train']
test_data = Data[Data['SPLIT'] == 'test']
test_scaffold = Data[Data['SPLIT'] == 'test_scaffolds']

all_syms = sorted(list(chars) + ['<bos>', '<eos>', '<pad>', '<unk>'])
vocabulary = all_syms

c2i = {c: i for i, c in enumerate(all_syms)}
i2c = {i: c for i, c in enumerate(all_syms)}

train_data = (train_data['SMILES'].squeeze()).astype(str).tolist()
test_scaffold = (test_scaffold['SMILES'].squeeze()).astype(str).tolist()
test_data = (test_data['SMILES'].squeeze()).astype(str).tolist()
