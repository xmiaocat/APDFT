#!/usr/bin/env python
import pytest
import glob
import os
import shutil

import numpy as np

import mqm
import mqm.Derivatives as mqmd
import mqm.Calculator as mqmc

@pytest.fixture
def mock_derivatives():
	c = mqmc.MockCalculator()
	d = mqmd.Derivatives(c, 0, [2, 2], np.array([[0, 0, 1], [0, 0, 2]]), 'HF', 'STO-3G')
	return d

@pytest.fixture(scope="module")
def sample_rundir():
	tmpdir = os.path.abspath(mqmc.Calculator._get_tempname())
	path = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
	shutil.copytree(path + '/data/multiqm-run', '%s/multiqm-run' % tmpdir)
	yield tmpdir
	shutil.rmtree('%s/multiqm-run' % tmpdir)

def test_readfile(sample_rundir):
	pwd = os.path.abspath(os.getcwd())
	os.chdir(sample_rundir)

	calculator = mqmc.GaussianCalculator()
	nuclear_numbers, coordinates = mqm.read_xyz('multiqm-run/n2.xyz')

	derivatives = mqm.Derivatives.DerivativeFolders(calculator, 2, nuclear_numbers, coordinates, 'HF', 'STO-3G')
	targets, energies, comparison_energies = derivatives.analyse(explicit_reference=True)

	# check one energy value
	lookup  = [1, 13]
	pos = targets.index(lookup)
	assert abs(energies[pos] - -160.15390113953077) < 1e-7
	assert abs(comparison_energies[pos] - -177.78263968061) < 1e-7

	os.chdir(pwd)

def test_grid():
	c = mqmc.MockCalculator()
	d = mqmd.Derivatives(c, 0, [1, 1], [[0, 0, 1], [0, 0, 2]], 'HF', 'STO-3G')
	coords, weights = d._get_grid()
	center = np.average(coords, axis=0)
	assert center[0] - 0 < 1e-8
	assert center[1] - 0 < 1e-8
	assert center[2] - 1.5 < 1e-8

def test_targets(mock_derivatives):
	targets = set([tuple(_) for _ in mock_derivatives._enumerate_all_targets()])
	expected = set([(0, 4), (1, 3), (2, 2), (3, 1), (4, 0)])
	assert targets == expected

def test_nucnuc(mock_derivatives):
	diff = mock_derivatives.calculate_delta_nuc_nuc(np.array([1, 3]))
	expected = -0.52917721067
	assert abs(diff - expected) < 1e-8

def test_filecontents():
	pwd = os.path.abspath(os.getcwd())
	tmpdir = os.path.abspath(mqmc.Calculator._get_tempname())
	os.mkdir(tmpdir)
	os.chdir(tmpdir)

	c = mqmc.GaussianCalculator()
	d = mqmd.DerivativeFolders(c, 2, [2, 3], np.array([[0, 0, 1], [0, 0, 2]]), 'HF', 'STO-3G')
	assert d._orders == [0, 1, 2]
	d.prepare(False)

	def _get_Zs_from_file(fn):
		with open(fn) as fh:
			lines = fh.readlines()[-2:]
		zs = [float(_.split()[-1]) for _ in lines]
		return zs

	delta = 0.05
	assert _get_Zs_from_file('multiqm-run/order-0/site-all-cc/run.inp') == [2., 3.]

	assert _get_Zs_from_file('multiqm-run/order-1/site-0-up/run.inp') == [2.+delta, 3.]
	assert _get_Zs_from_file('multiqm-run/order-1/site-0-dn/run.inp') == [2.-delta, 3.]
	assert _get_Zs_from_file('multiqm-run/order-1/site-1-up/run.inp') == [2., 3.+delta]
	assert _get_Zs_from_file('multiqm-run/order-1/site-1-dn/run.inp') == [2., 3.-delta]

	assert _get_Zs_from_file('multiqm-run/order-2/site-0-0-up/run.inp') == [2.+delta, 3.]
	assert _get_Zs_from_file('multiqm-run/order-2/site-0-0-dn/run.inp') == [2.-delta, 3.]
	assert _get_Zs_from_file('multiqm-run/order-2/site-1-1-up/run.inp') == [2., 3.+delta]
	assert _get_Zs_from_file('multiqm-run/order-2/site-1-1-dn/run.inp') == [2., 3.-delta]
	assert _get_Zs_from_file('multiqm-run/order-2/site-0-1-up/run.inp') == [2.+delta, 3.+delta]
	assert _get_Zs_from_file('multiqm-run/order-2/site-0-1-dn/run.inp') == [2.-delta, 3.-delta]

	assert set(map(os.path.basename, glob.glob('multiqm-run/*'))) == set('order-0 order-1 order-2'.split())
	assert set(map(os.path.basename, glob.glob('multiqm-run/order-0/*'))) == set('site-all-cc'.split())
	assert set(map(os.path.basename, glob.glob('multiqm-run/order-1/*'))) == set('site-0-up site-0-dn site-1-up site-1-dn'.split())
	assert set(map(os.path.basename, glob.glob('multiqm-run/order-2/*'))) == set('site-0-0-up site-0-0-dn site-1-1-up site-1-1-dn site-0-1-up site-0-1-dn'.split())

	os.chdir(pwd)
	shutil.rmtree(tmpdir)

def test_too_high_order():
	c = mqmc.GaussianCalculator()
	with pytest.raises(NotImplementedError):
		d = mqmd.DerivativeFolders(c, 3, [2, 3], np.array([[0, 0, 1], [0, 0, 2]]), 'HF', 'STO-3G')

def test_element_conversion():
	assert mqmd.Derivatives._Z_to_label(0) == "-"
	assert mqmd.Derivatives._Z_to_label(1) == "H"
	assert mqmd.Derivatives._Z_to_label(2) == "He"
