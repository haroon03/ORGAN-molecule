from Data import *
import unittest
import tqdm as tqdm
from Metrics_Reward import *
from Model import ORGAN


class test_metrics(unittest.TestCase):
    test = ['Oc1ccccc1-c1cccc2cnccc12',
            'COc1cccc(NC(=O)Cc2coc3ccc(OC)cc23)c1']
    test_sf = ['COCc1nnc(NC(=O)COc2ccc(C(C)(C)C)cc2)s1',
               'O=C(C1CC2C=CC1C2)N1CCOc2ccccc21',
               'Nc1c(Br)cccc1C(=O)Nc1ccncn1']
    gen = ['CNC', 'Oc1ccccc1-c1cccc2cnccc12',
           'INVALID', 'CCCP',
           'Cc1noc(C)c1CN(C)C(=O)Nc1cc(F)cc(F)c1',
           'Cc1nc(NCc2ccccc2)no1-c1ccccc1']
    target = {'valid': 2 / 3,
              'unique@3': 1.0,
              'FCD/Test': 52.58371754126664,
              'SNN/Test': 0.3152585653588176,
              'Frag/Test': 0.3,
              'Scaf/Test': 0.5,
              'IntDiv': 0.7189187309761661,
              'Filters': 0.75,
              'logP': 4.9581881764518005,
              'SA': 0.5086898026154574,
              'QED': 0.045033731661603064,
              'NP': 0.2902816615644048,
              'weight': 14761.927533455337}

    def test_get_all_metrics_multiprocess(self):
        metrics = get_all_metrics(test_data, samples, k=3)
        fail = set()
        for metric in self.target:
            if not np.allclose(metrics[metric], self.target[metric]):
                warnings.warn(
                    "Metric `{}` value does not match expected "
                    "value. Got {}, expected {}".format(metric,
                                                        metrics[metric],
                                                        self.target[metric])
            )
            fail.add(metric)
        assert len(fail) == 0, f"Some metrics didn't pass tests: {fail}"

    def test_get_all_metrics_scaffold(self):
        get_all_metrics(self.test, self.gen,
                        test_scaffolds=self.test_sf,
                        k=3, n_jobs=2)
        mols = ['CCNC', 'CCC', 'INVALID', 'CCC']
        assert np.allclose(fraction_valid(mols), 3 / 4), "Failed valid"
        assert np.allclose(fraction_unique(mols, check_validity=False),
                           3 / 4), "Failed unique"
        assert np.allclose(fraction_unique(mols, k=2), 1), "Failed unique"
        mols = [Chem.MolFromSmiles(x) for x in mols]
        assert np.allclose(fraction_valid(mols), 3 / 4), "Failed valid"
        assert np.allclose(fraction_unique(mols, check_validity=False),
                           3 / 4), "Failed unique"
        assert np.allclose(fraction_unique(mols, k=2), 1), "Failed unique"


def sampler(model):
    n_samples = 100000
    samples = []
    with tqdm(total=n_samples, desc='Generating Samples')as T:
        while n_samples > 0:
            current_samples = model.sample(min(n_samples, 64), max_length=100)
            samples.extend(current_samples)
            n_samples -= len(current_samples)
            T.update(len(current_samples))

    return samples


def evaluate(test, samples, test_scaffolds=None, ptest=None, ptest_scaffolds=None):
    gen = samples
    k = [50, 99]
    n_jobs = 1
    batch_size = 20
    ptest = ptest
    ptest_scaffolds = 20
    pool = None
    gpu = None
    metrics = get_all_metrics(test, gen, k, n_jobs, device, batch_size, test_scaffolds, ptest, ptest_scaffolds)
    for name, value in metrics.items():
        print('{}, {}'.format(name, value))


model = ORGAN()
samples = sampler(model)
model = model.to(device)
evaluate(test_data, samples)

