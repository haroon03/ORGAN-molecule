import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

from Data import *
from Metrics_Reward import MetricsReward


class Generator(nn.Module):
    def __init__(self, embedding_layer, hidden_size, num_layers, dropout):
        super(Generator, self).__init__()

        self.embedding_layer = embedding_layer
        self.lstm_layer = nn.LSTM(embedding_layer.embedding_dim,
                                  hidden_size, num_layers,
                                  batch_first=True, dropout=dropout)
        self.linear_layer = nn.Linear(hidden_size,
                                      embedding_layer.num_embeddings)

    def forward(self, x, lengths, states=None):
        x = self.embedding_layer(x)
        x = pack_padded_sequence(x, lengths, batch_first=True)
        x, states = self.lstm_layer(x, states)
        x, _ = pad_packed_sequence(x, batch_first=True)
        x = self.linear_layer(x)

        return x, lengths, states


class Discriminator(nn.Module):
    def __init__(self, desc_embedding_layer, convs, dropout=0):
        super(Discriminator, self).__init__()

        self.embedding_layer = desc_embedding_layer
        self.conv_layers = nn.ModuleList(
            [nn.Conv2d(1, f, kernel_size=(
                n, self.embedding_layer.embedding_dim)
                       ) for f, n in convs])
        sum_filters = sum([f for f, _ in convs])
        self.highway_layer = nn.Linear(sum_filters, sum_filters)
        self.dropout_layer = nn.Dropout(p=dropout)
        self.output_layer = nn.Linear(sum_filters, 1)

    def forward(self, x):
        x = self.embedding_layer(x)
        x = x.unsqueeze(1)
        convs = [F.elu(conv_layer(x)).squeeze(3)
                 for conv_layer in self.conv_layers]
        x = [F.max_pool1d(c, c.shape[2]).squeeze(2) for c in convs]
        x = torch.cat(x, dim=1)

        h = self.highway_layer(x)
        t = torch.sigmoid(h)
        x = t * F.elu(h) + (1 - t) * x
        x = self.dropout_layer(x)
        out = self.output_layer(x)

        return out


class ORGAN(nn.Module):
    def __init__(self):
        super(ORGAN, self).__init__()

        self.metrics_reward = MetricsReward(n_ref_subsample=100, n_rollouts=16, n_jobs=1, metrics=[])

        self.reward_weight = 0.7

        self.convs = [(100, 1), (200, 2), (200, 3),
                 (200, 4), (200, 5), (100, 6),
                 (100, 7), (100, 8), (100, 9),
                 (100, 10)]

        self.embedding_layer = nn.Embedding(
            len(vocabulary), embedding_dim=32, padding_idx=c2i['<pad>'])

        self.desc_embedding_layer = nn.Embedding(
            len(vocabulary), embedding_dim=32, padding_idx=c2i['<pad>'])

        self.generator = Generator(self.embedding_layer, hidden_size=512, num_layers=2, dropout=0)

        self.discriminator = Discriminator(self.desc_embedding_layer, self.convs, dropout=0)

    def device(self):
        return next(self.parameters()).device

    def generator_forward(self, *args, **kwargs):
        return self.generator(*args, **kwargs)

    def discriminator_forward(self, *args, **kwargs):
        return self.discriminator(*args, **kwargs)

    def forward(self, *args, **kwargs):
        return self.sample(*args, **kwargs)

    def char2id(self, c):
        if c not in c2i:
            return c2i['<unk>']

        return c2i[c]

    def id2char(self, id):
        if id not in i2c:
            return i2c[14]

        return i2c[id]

    def string2id(self, string, add_bos=False, add_eos=False):
        ids = [self.char2id(c) for c in string]

        if add_bos:
            ids = [c2i['<bos>']] + ids

        if add_eos:
            ids = ids + [c2i['<eos>']]

        return ids

    def ids2string(self, ids, rem_bos=True, rem_eos=True):
        if len(ids) == 0:
            return ''
        if rem_bos and ids[0] == c2i['<bos>']:
            ids = ids[1:]
        if rem_eos and ids[-1] == c2i['<eos>']:
            ids = ids[:-1]

        string = ''.join([self.id2char(id) for id in ids])

        return string

    def string2tensor(self, string):
        ids = self.string2id(string, add_bos=True, add_eos=True)
        tensor = torch.tensor(ids, dtype=torch.long, device=device)

        return tensor

    def tensor2string(self, tensor):
        ids = tensor.tolist()
        string = self.ids2string(ids, rem_bos=True, rem_eos=True)

        return string

    def sample_tensor(self, n, max_length=100):
        prevs = torch.empty(n, 1,
                            dtype=torch.long).fill_(c2i['<bos>'])
        samples, lengths = self._proceed_sequences(prevs, None, max_length)

        samples = torch.cat([prevs, samples], dim=-1)
        lengths += 1

        return samples, lengths

    def sample(self, batch_n=64, max_length=100):
        samples, lengths = self.sample_tensor(batch_n, max_length)
        samples = [t[:l] for t, l in zip(samples, lengths)]

        return [self.tensor2string(t) for t in samples]

    def _proceed_sequences(self, prevs, states, max_length):
        with torch.no_grad():
            n_sequences = prevs.shape[0]

            sequences = []
            lengths = torch.zeros(n_sequences,
                                  dtype=torch.long, device=device)

            one_lens = torch.ones(n_sequences,
                                  dtype=torch.long, device=device)
            is_end = prevs.eq(c2i['<eos>']).view(-1)

            for _ in range(max_length):
                outputs, _, states = self.generator(prevs, one_lens, states)
                probs = F.softmax(outputs, dim=-1).view(n_sequences, -1)
                currents = torch.multinomial(probs, 1)

                currents[is_end, :] = c2i['<pad>']
                sequences.append(currents)
                lengths[~is_end] += 1

                is_end[currents.view(-1) == c2i['<eos>']] = 1
                if is_end.sum() == n_sequences:
                    break

                prevs = currents

            sequences = torch.cat(sequences, dim=-1)

        return sequences, lengths

    def rollout(self, ref_smiles, ref_mols, n_samples, n_rollouts, max_length=100):
        with torch.no_grad():
            sequences = []
            rewards = []
            ref_smiles = ref_smiles
            ref_mols = ref_mols
            lengths = torch.zeros(n_samples, dtype=torch.long, device=device)

            one_lens = torch.ones(n_samples, dtype=torch.long, )
            prevs = torch.empty(n_samples, 1, dtype=torch.long, device=device).fill_(c2i['<bos>'])
            is_end = torch.zeros(n_samples, dtype=torch.uint8, device=device)
            states = None

            sequences.append(prevs)
            lengths += 1

            for current_len in range(10):
                print(current_len)
                outputs, _, states = self.generator(prevs, one_lens, states)

                probs = F.softmax(outputs, dim=-1).view(n_samples, -1)
                currents = torch.multinomial(probs, 1)

                currents[is_end, :] = c2i['<pad>']
                sequences.append(currents)
                lengths[~is_end] += 1

                rollout_prevs = currents[~is_end, :].repeat(n_rollouts, 1)
                rollout_states = (
                    states[0][:, ~is_end, :].repeat(1, n_rollouts, 1),
                    states[1][:, ~is_end, :].repeat(1, n_rollouts, 1)
                )
                rollout_sequences, rollout_lengths = self._proceed_sequences(
                    rollout_prevs, rollout_states, max_length - current_len
                )

                rollout_sequences = torch.cat(
                    [s[~is_end, :].repeat(n_rollouts, 1) for s in sequences] + [rollout_sequences], dim=-1)
                rollout_lengths += lengths[~is_end].repeat(n_rollouts)

                rollout_rewards = torch.sigmoid(
                    self.discriminator(rollout_sequences).detach()
                )

                if self.metrics_reward is not None and self.reward_weight > 0:
                    strings = [
                        self.tensor2string(t[:l])
                        for t, l in zip(rollout_sequences, rollout_lengths)
                    ]

                    obj_rewards = torch.tensor(
                        self.metrics_reward(strings, ref_smiles, ref_mols)).view(-1, 1)
                    rollout_rewards = (rollout_rewards * (1 - self.reward_weight) +
                                       obj_rewards * self.reward_weight
                                       )
                print('Metrics Rewards = ', obj_rewards)
                current_rewards = torch.zeros(n_samples, device=device)

                current_rewards[~is_end] = rollout_rewards.view(
                    n_rollouts, -1
                ).mean(dim=0)
                rewards.append(current_rewards.view(-1, 1))

                is_end[currents.view(-1) == c2i['<eos>']] = 1
                if is_end.sum() >= 10:
                    break
                prevs = currents

            sequences = torch.cat(sequences, dim=1)
            rewards = torch.cat(rewards, dim=1)

        return sequences, rewards, lengths
      
