#!/usr/bin/env python
# Story APDFT#248
# Question APDFT#249: Are ANM locally optimal representations, i.e. is there an orthogonal transformation such that learning naphthalene gets better?
# References:
#  - Generalized Euler angles, 10.1063/1.1666011

#%%
# AD
# keep jax config first
from jax.config import config

config.update("jax_enable_x64", True)
import jax
import jax.numpy as jnp

# Test for double precision import
x = jax.random.uniform(jax.random.PRNGKey(0), (1,), dtype=jnp.float64)
assert x.dtype == jnp.dtype("float64"), "JAX not in double precision mode"

import qml
import requests

import numpy as np
import matplotlib.pyplot as plt
import functools
import pandas as pd

anmhessian = np.loadtxt("hessian.txt")
_, anmvectors = np.linalg.eig(anmhessian)

sys.path.append("..")
import mlmeta

# %%
def gea_matrix_a(angles):
    """
    Generalized Euler Angles
    Return the parametric angles described on Eqs. 15-19 from the paper:
    Generalization of Euler Angles to N-Dimensional Orthogonal Matrices
    David K. Hoffman, Richard C. Raffenetti, and Klaus Ruedenberg
    Journal of Mathematical Physics 13, 528 (1972)
    doi: 10.1063/1.1666011
    """
    n = len(angles)
    matrix_a = jnp.eye(n)

    for i in range(n - 1):
        matrix_a = matrix_a.at[i, i].set(jnp.cos(angles[i]))
        matrix_a = matrix_a.at[i, n - 1].set(jnp.tan(angles[i]))
        for j in range(i + 1):
            matrix_a = matrix_a.at[i, n - 1].mul(jnp.cos(angles[j]))

    for i in range(n):
        for k in range(n - 1):
            if i > k:
                matrix_a = matrix_a.at[i, k].set(
                    -jnp.tan(angles[i]) * jnp.tan(angles[k])
                )
                for l in range(k, i + 1):
                    matrix_a = matrix_a.at[i, k].mul(jnp.cos(angles[l]))

    matrix_a = matrix_a.at[n - 1, n - 1].set(jnp.tan(angles[n - 1]))
    for j in range(n):
        matrix_a = matrix_a.at[n - 1, n - 1].mul(jnp.cos(angles[j]))

    return matrix_a


def gea_orthogonal_from_angles(angles_list):
    """
    Generalized Euler Angles
    Return the orthogonal matrix from its generalized angles
    Generalization of Euler Angles to N-Dimensional Orthogonal Matrices
    David K. Hoffman, Richard C. Raffenetti, and Klaus Ruedenberg
    Journal of Mathematical Physics 13, 528 (1972)
    doi: 10.1063/1.1666011
    :param angles_list: List of angles, for a n-dimensional space the total number
                        of angles is k*(k-1)/2
    """

    b = jnp.eye(2)
    n = int(jnp.sqrt(len(angles_list) * 8 + 1) / 2 + 0.5)
    tmp = jnp.array(angles_list)

    # For SO(k) there are k*(k-1)/2 angles that are grouped in k-1 sets
    # { (k-1 angles), (k-2 angles), ... , (1 angle)}
    for i in range(1, n):
        angles = jnp.concatenate((jnp.array(tmp[-i:]), jnp.array([jnp.pi / 2])))
        tmp = tmp[:-i]
        ma = gea_matrix_a(angles)  # matrix i+1 x i+1
        b = jnp.dot(b, ma.T).T
        # We skip doing making a larger matrix for the last iteration
        if i < n - 1:
            c = jnp.eye(i + 2, i + 2)
            c = c.at[:-1, :-1].set(b)
            b = c
    return b


# %%
@functools.lru_cache(maxsize=1)
def fetch_energies():
    """Loads CCSD/cc-pVDZ energies.

    Returns
    -------
    DataFrame
        Energies and metadata
    """
    df = pd.read_csv("https://zenodo.org/record/3994178/files/reference.csv?download=1")
    C = -37.69831437
    B = -24.58850790
    N = -54.36533180
    df["totalE"] = df.CCSDenergyinHa.values
    df["nuclearE"] = df.NNinteractioninHa.values
    df["electronicE"] = df.totalE.values - df.nuclearE.values

    # atomisation energy
    atoms = (10 - 2 * df.nBN.values) * C + df.nBN.values * (B + N)
    df["atomicE"] = df.totalE.values - atoms

    df = df["label nBN totalE nuclearE electronicE atomicE".split()].copy()
    return df


def get_rep(transformation, mol):
    dz = jnp.array(mol.nuclear_charges[:10]) - 6
    return jnp.dot(jnp.dot(transformation, anmvectors.T), dz)


#%%
@functools.lru_cache(maxsize=1)
def fetch_geometry():
    """Loads the XYZ geometry for naphthalene used in the reference calculations.

    Returns
    -------
    str
        XYZ file contents, ascii.
    """
    res = requests.get("https://zenodo.org/record/3994178/files/inp.xyz?download=1")
    return res.content.decode("ascii")


# endregion
# region cached ML boilerplate
class MockXYZ(object):
    def __init__(self, lines):
        self._lines = lines

    def readlines(self):
        return self._lines


@functools.lru_cache(maxsize=3000)
def get_compound(label):
    c = qml.Compound(xyz=MockXYZ(fetch_geometry().split("\n")))
    c.nuclear_charges = [int(_) for _ in str(label)] + [1] * 8
    return c


#%%
def ds(reps):
    def outer(i, K):
        def inner(j, K):
            d = jnp.linalg.norm(reps[i] - reps[j])
            K = K.at[i, j].set(d)
            K = K.at[j, i].set(d)
            return K

        return jax.lax.fori_loop(i, nmols, inner, K)

    nmols = len(reps)
    K = jnp.zeros((nmols, nmols))
    return jax.lax.fori_loop(0, nmols, outer, K)


# %%


def get_lc_endpoint(df, transformation, propname):
    X = jnp.array([get_rep(transformation, get_compound(_)) for _ in df.label.values])
    Y = df[propname].values

    totalidx = np.arange(len(X), dtype=np.int)
    maes = []

    dscache = ds(X)
    for sigma in (1.0,):  # 2.0 ** np.arange(-2, 10):
        inv_sigma = -0.5 / (sigma * sigma)
        Ktotal = jnp.exp(dscache * inv_sigma)

        mae = []
        for ntrain in (2048,):
            for k in range(1):
                np.random.shuffle(totalidx)
                train, test = totalidx[:ntrain], totalidx[ntrain:]

                lval = 10 ** -10
                K_subset = Ktotal[np.ix_(train, train)]
                K_subset = K_subset.at[np.diag_indices_from(K_subset)].add(lval)
                step1 = jax.scipy.linalg.cho_factor(K_subset)
                alphas = jax.scipy.linalg.cho_solve(step1, Y[train])

                K_subset = Ktotal[np.ix_(train, test)]
                pred = jnp.dot(K_subset.transpose(), alphas)
                actual = Y[test]

                thismae = jnp.abs(pred - actual).mean()
                mae.append(thismae)
        maes.append(jnp.average(mae))
    return jnp.min(jnp.array(maes))


def wrapper(angles):
    transform = gea_orthogonal_from_angles(angles)
    return get_lc_endpoint(fetch_energies(), transform, "atomicE")


def doit():
    angles = np.zeros(45)
    angles[0] = 0.1
    angles = jnp.array(angles)
    print(wrapper(angles))


# doit()
# %%
mlmeta.profile(doit)
# %%
