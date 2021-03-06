from scipy.spatial.distance import pdist
from pandas import DataFrame, concat
from numpy import array as npa
from numpy import repeat, isscalar, atleast_2d, mean, linspace, concatenate,\
                  empty, diag, vstack, arange
from numpy.random import RandomState
from jbutils import cartesian, rank, cmap_discrete, jbpickle, jbunpickle,\
                    make_domain_grid
from jbgp_1d import K_se, conditioned_mu, conditioned_covmat
from matplotlib import pyplot as plt
from jbutils import make_domain_grid
import pdb

def demo(plot):
    if not plot: plot=False
    DISTTYPE = 'x'
    NEXP = 200
    NOBS = 3
    LENSCALEPOOL = [2.**-n for n in [2., 4., 6.]]
    DOMAINBOUNDS = [[0., 1.]]
    DOMAINRES = [100]
    DOMAIN = make_domain_grid(DOMAINBOUNDS, DOMAINRES).flatten()
    EDGEBUF = 0.05 # samples for 2sams wont be closer than EDGEBUF from screen edge
    XSAM_BOUNDS = DOMAINBOUNDS
    XSAM_BOUNDS[0][0] = EDGEBUF
    XSAM_BOUNDS[0][1] -= EDGEBUF
    SIGVAR = 1.
    NOISEVAR = 1e-7
    NTOTEST = 10000
    RNGSEED = None

    fardistobs = generate_fardists(DISTTYPE, NEXP, NOBS, LENSCALEPOOL, DOMAIN,\
                                   XSAM_BOUNDS, SIGVAR, NOISEVAR, NTOTEST, RNGSEED)

    if plot:
        # plot
        xobs = fardistobs['xObs']
        yobs = fardistobs['yObs']

        plotdemo = lambda iexp: plot_fardists(DOMAIN, xobs[iexp], yobs[iexp], LENSCALEPOOL)

        resp = {'fardistobs': fardistobs,
                'plotdemo': plotdemo}
    else:
        resp = fardistobs

    return resp


def generate_fardists(distType, nToKeep, nObs, lenscalepool, domain, xSam_bounds,\
                      sigvar=None, noisevar=None, nToTest=None, rng=None):

    if not sigvar: sigvar = 1.
    if not noisevar: noisevar = 1e-7
    if not nToTest: nToTest = nToKeep*100

    # generate random valid loc-val pairs for experiments

    obs = generate_rand_obs(nToTest, nObs, xSam_bounds, sigvar, rng)
    xObs = obs['x']
    yObs = obs['y']

    # get loc-val of maxev for each lengthscale for each experiment
    evmaxes = [get_evmax(xObs, yObs, domain, lenscale, sigvar, noisevar)
               for lenscale in lenscalepool]

    # get average distance between maxes for each lenscale
    iExp_rankedByDist = get_ranked_dists(evmaxes, distType)

    # take only the top n ranked dists
    usedExps = [iexp for iexp in iExp_rankedByDist
                if iExp_rankedByDist[iexp]['rank'] < nToKeep]
    xObs_queue = xObs[usedExps]
    yObs_queue = yObs[usedExps]
    return {'xObs': xObs_queue,
            'yObs': yObs_queue}


def generate_rand_obs(nExp, nObs, domainBounds, sigvar=None, rng=None):
    # create random sets of observations for each experiment
    if not sigvar: sigvar = 1.
    if not rng: rng = RandomState()

    domainBounds = npa(domainBounds)
    minX = domainBounds[:, 0]
    maxX = domainBounds[:, 1]
    rangeX = maxX - minX
    xObs = rng.uniform(size=(nExp, nObs))
    xObs *= rangeX
    xObs += minX
    yObs = empty(shape=(nExp, nObs))
    for iexp in xrange(nExp):
        good = False
        while not good:
            yObs0 = rng.normal(size=(nObs))
            if yObs0.max() > 0: good = True
        yObs[iexp, :] = yObs0
    # yObs = rng.normal(size=(nExp, nObs, 1))
    yObs *= sigvar

    return {'x': xObs,  # make 1d
            'y': yObs}


def get_evmax(xObs, yObs, domain, lenscale, sigvar=None, noisevar=None):
    """currently, nObs needs to be constant (i.e. xObs and yObs need to be
        rectangular 2-tensors of shape (nExp x nObs) )"""
    if not sigvar: sigvar=1.
    if not noisevar: noisevar=1e-7  # default noiseless
    assert len(xObs.shape) == 2, 'dim xObs must = 2 (nExp x nObs)'
    assert len(domain.shape) == 1, 'dim domain must = 1'

    nExp, nObs = xObs.shape  # unpack

    # get conditioned posteriors
    print 'lenscale: ' + str(lenscale)
    postmus = (conditioned_mu(domain, xObs[iexp], yObs[iexp],\
                              lenscale, sigvar, noisevar)
               for iexp in xrange(nExp))
    # get maxes of posteriors
    imaxes = []
    xmaxes = []
    fmaxes = []
    for postmu in postmus:
        imax = postmu.argmax()
        imaxes.append(imax)# nExp x 1
        xmaxes.append(domain[imax])  # nExp x 1
        fmaxes.append(postmu[imax])  # nExp x 1
    # add experiment metadata for call to get_ranked_dists
    imaxes = npa(imaxes)
    fmaxes = npa(fmaxes)
    lenscales = [lenscale] * nExp
    iExps = arange(nExp)

    return {'xmax': xmaxes,
            'fmax': fmaxes,
            'imax': imaxes,
            'lenscale': lenscales,
            'iExp': iExps}


def get_ranked_dists(evmaxes, distType):
    """evmaxes is a lodicts generated with [get_evmax(...,ls,...) for ls in lenscalepool].
    each evmaxes[i][j] must have keys [xmax, fmax, iExp].
    Returns dict with iExp and dist rank for iExp for each experimetn iExp,
    with distance metric determined by param distType in ['x', 'f', 'xXf']"""

    assert distType in ['x', 'f', 'xXf']

    # put into dataframe format
    evmaxes = [DataFrame(lsevmax) for lsevmax in evmaxes]  # make each ls dataframe
    evmaxes = concat(evmaxes)  # combine dataframes

    # make distance function based on param distType
    if distType=='x':
        dfcn = lambda df0: mu_lnnorm(df0.xmax.values)
    elif distType=='f':
        dfcn = lambda df0: mu_lnnorm(df0.fmax.values)
    elif distType=='xXf':
        dfcn = lambda df0: mu_lnnorm(df0.fmax.values) *\
                           mu_lnnorm(df0.xmax.values)

    # get dist bt lenscale conds for each experiment iExp
    dfDists = evmaxes.groupby('iExp').apply(dfcn).reset_index()
    dfDists.rename(columns={0:'dist'}, inplace=True)
    dfDists['rank'] = rank(dfDists['dist'].values, descending=True)  # rank by dist
    dfDists['distType'] = distType

    # return as dict, not df
    usedFields = ['iExp', 'dist', 'rank', 'distType']
    iExps, dists, ranks, distTypes = [dfDists[f].values for f in usedFields]
    out = {iExp: {'dist': dists[ii], 'rank': ranks[ii], 'distType':distTypes[ii]}
           for ii, iExp in enumerate(iExps)}

    # out = {}
    # for ii, iExp in enumerate(iExps):
    #     out[iExp] = {'dist': dists[ii],
    #                  'rank': ranks[ii],
    #                  'distType': distTypes[ii]}
    return out


def get_obsNTopFar(N, evmaxes, iExp_rankedByDist):
    # filter to top N experiments with farthest distanced
    usedExps = [iexp for iexp in iExp_rankedByDist
                if iExp_rankedByDist[iexp]['rank'] < N]

    evmax = evmaxes[0]  # pick arbitrary lenscale from which to take obs
    # function to extract only obs from an experiment
    get_obs = lambda elt: {'xObs': elt['xObs'], 'yObs': elt['yObs']}
    # get the obss from exps that had highest mean dist for max bt lenscales
    out = [get_obs(exp) for exp in evmax if exp['iExp'] in usedExps]
    return out


def mu_lnnorm(v, n=2):
    """v is a 1d array_like.  gives the average pair-wise l_n-norm distance
    between all elts in v"""
    assert len(v.shape) == 1
    pairwise_dists = pdist(zip(v), p=n)
    return mean(pairwise_dists)


def plot_fardists(domain, xObs, yObs, lenscalepool, sigvar=1., noisevar=1e-7, cmap='autumn'):
    fig, ax = plt.subplots()
    ax.plot(xObs, yObs,\
            marker='o', color='black', mec='None', ls='None', alpha=0.3, markersize=10)
    nls = len(lenscalepool)
    cols = cmap_discrete(nls+2, cmap)
    for ils in xrange(nls):
        ls = lenscalepool[ils]
        postmu = conditioned_mu(domain, xObs, yObs, ls, sigvar, noisevar)
        kDomain = K_se(domain, domain, ls, sigvar)
        postcv = conditioned_covmat(domain, kDomain, xObs, ls, sigvar, noisevar)
        postsd = diag(postcv)
        col = cols[ils+1]
        ax.fill_between(domain.flatten(), postmu+postsd, postmu-postsd,\
                         facecolor=col, edgecolor='None', alpha=0.1)
        ax.plot(domain.flatten(), postmu, color=col)
        imax = postmu.argmax()
        xmax = domain[imax]
        ymax = postmu[imax]
        ax.plot(xmax, ymax,\
                 marker='o', color=col, mec='None', alpha=0.5, markersize=8)
    return (fig, ax)

def plot_sam(domain, xObs, yObs, lenscalepool, sigvar=1., noisevar=1e-7, cmap='autumn'):
    fig, ax = plt.subplots()
    # ax.plot(xObs, yObs,\
    #         marker='o', color='black', mec='None', ls='None', alpha=0.3, markersize=10)
    nls = len(lenscalepool)
    cols = cmap_discrete(nls+2, cmap)
    for ils in [1]:
        ls = lenscalepool[ils]
        postmu = conditioned_mu(domain, xObs, yObs, ls, sigvar, noisevar)
        kDomain = K_se(domain, domain, ls, sigvar)
        postcv = conditioned_covmat(domain, kDomain, xObs, ls, sigvar, noisevar)
        postsd = diag(postcv)
        col = cols[ils+1]
        ax.fill_between(domain.flatten(), postmu+postsd, postmu-postsd,\
                         facecolor=col, edgecolor='None', alpha=0.1)
        ax.plot(domain.flatten(), postmu, color=col)
        imax = postmu.argmax()
        xmax = domain[imax]
        ymax = postmu[imax]
        # ax.plot(xmax, ymax,\
        #          marker='o', color=col, mec='None', alpha=0.5, markersize=8)
    return (fig, ax)

# def prep_for_gpy(x, dimX):
#     """def prep_for_gpy(x, dimX)

#     ensures obs matrix x, with expected input dim dimX, is properly
#     formatted to work with GPy"""

#     # prep observations if 1d
#     if dimX == 1:
#         x = atleast_2d(x)
#     assert len(x.shape)==2
#     if x.shape[1] != dimX: x = x.T
#     assert x.shape[1] == dimX
#     return x
