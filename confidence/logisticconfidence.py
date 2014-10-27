# modelconfidence.py

# Uses internal evidence in page-level predictions, plus metadata, to produce
# a model of accuracy for these predictions.

import json
import os, sys
import numpy as np
import pandas as pd
import SonicScrewdriver as utils
from sklearn.linear_model import LogisticRegression
from sklearn import cross_validation
from scipy.stats.stats import pearsonr

genretranslations = {'subsc' : 'front', 'argum': 'non', 'pref': 'non', 'aut': 'bio', 'bio': 'bio', 'toc': 'front', 'title': 'front', 'bookp': 'front', 'bibli': 'ads', 'gloss': 'back', 'epi': 'fic', 'errat': 'non', 'notes': 'non', 'ora': 'non', 'let': 'bio', 'trv': 'non', 'lyr': 'poe', 'nar': 'poe', 'vdr': 'dra', 'pdr': 'dra', 'clo': 'dra', 'impri': 'front', 'libra': 'back', 'index': 'back'}

def sequence_to_counts(genresequence):
    '''Converts a sequence of page-level predictions to
    a dictionary of counts reflecting the number of pages
    assigned to each genre. Also reports the largest genre.
    Note that this function cannot return "bio." If
    biography is the largest genre it returns "non"fiction.
    It counts bio, but ensures that all votes for bio are also votes
    for non.
    '''

    genrecounts = dict()

    for page in genresequence:
        utils.addtodict(page, 1, genrecounts)
        if page == 'bio':
            utils.addtodict('non', 1, genrecounts)

    # Convert the dictionary of counts into a sorted list, and take the max.
    genretuples = utils.sortkeysbyvalue(genrecounts, whethertoreverse = True)
    maxgenre = genretuples[0][1]

    if maxgenre == 'bio':
        maxgenre = 'non'

    return genrecounts, maxgenre

def count_flips(sequence):
    numflips = 0
    prevgenre = ""
    for genre in sequence:
        if genre != prevgenre:
            numflips += 1

        prevgenre = genre

    return numflips

def normalizearray(featurearray):
    '''Normalizes an array by centering on means and
    scaling by standard deviations.
    '''

    numinstances, numfeatures = featurearray.shape
    means = list()
    stdevs = list()
    for featureidx in range(numfeatures):
        thiscolumn = featurearray[ : , featureidx]
        thismean = np.mean(thiscolumn)
        means.append(thismean)
        thisstdev = np.std(thiscolumn)
        stdevs.append(thisstdev)
        featurearray[ : , featureidx] = (thiscolumn - thismean) / thisstdev

    return featurearray

def binarize(accuracies, threshold=0.95):
    binarized = list()
    for val in accuracies:
        if val > threshold:
            binarized.append(1)
        else:
            binarized.append(0)
    return binarized

class Prediction:

    def __init__(self, filepath):
        with open(filepath, encoding='utf-8') as f:
            filelines = f.readlines()
        jsonobject = json.loads(filelines[0])
        self.dirtyid = jsonobject['volID']
        self.rawPredictions = jsonobject['rawPredictions']
        self.smoothPredictions = jsonobject['smoothedPredictions']
        self.probabilities = jsonobject['smoothedProbabilities']
        self.avggap = jsonobject['avgGap']
        self.maxprob = jsonobject['avgMaxProb']
        self.pagelen = len(self.smoothPredictions)

        self.genrecounts, self.maxgenre = sequence_to_counts(self.smoothPredictions)
        pagesinmax = self.genrecounts[self.maxgenre]
        self.maxratio = pagesinmax / self.pagelen

        self.rawflipratio = (count_flips(self.rawPredictions) / self.pagelen)
        self.smoothflips = count_flips(self.smoothPredictions)

        if 'bio' in self.genrecounts and self.genrecounts['bio'] > (self.pagelen / 2):
            self.bioflag = True
        else:
            self.bioflag = False

    def addmetadata(self, row, table):
        self.author = table['author'][row]
        self.title = table['title'][row]
        self.date = utils.simple_date(row, table)
        genrelist = table['genres'][row].split(';')
        self.genres = set(genrelist)

        varietiesofnon = ['Bibliographies', 'Catalog', 'Dictionary', 'Encyclopedia', 'Handbooks', 'Indexes', 'Legislation', 'Directories', 'Statistics', 'Legal cases', 'Legal articles', 'Calendars', 'Autobiography', 'Biography', 'Letters', 'Essays', 'Speeches']

        self.nonmetaflag = False
        for genre in varietiesofnon:
            if genre in self.genres:
                self.nonmetaflag = True

    def missingmetadata(self):
        self.author = ''
        self.title = ''
        self.date = ''
        self.genres = set()
        self.nonmetaflag = False

    def getfeatures(self):

        features = np.zeros(13)

        if self.maxgenre == 'fic':

            if 'Fiction' in self.genres or 'Novel' in self.genres or 'Short stories' in self.genres:
                features[0] = 1

            if 'Drama' in self.genres or 'Poetry' in self.genres or self.nonmetaflag:
                features[1] = 1

        if self.maxgenre == 'poe':

            if 'Poetry' in self.genres or 'poems' in self.title.lower():
                features[2] = 1

            if 'Drama' in self.genres or 'Fiction' in self.genres or self.nonmetaflag:
                features[3] = 1

        if self.maxgenre == 'dra':
            if 'Drama' in self.genres or 'plays' in self.title.lower():
                features[4] = 1

            if 'Fiction' in self.genres or 'Poetry' in self.genres or self.nonmetaflag:
                features[5] = 1

        if self.maxgenre == 'non':

            if self.nonmetaflag:
                features[6] = 1

            if 'Fiction' in self.genres or 'Poetry' in self.genres or 'Drama' in self.genres or 'Novel' in self.genres or 'Short stories' in self.genres:
                features[7] = 1

        features[8] = self.maxratio
        features[9] = self.rawflipratio
        features[10] = self.smoothflips
        features[11] = self.avggap
        features[12] = self.maxprob

        return features

    def genrefeatures(self, agenre):
        ''' Extracts features to characterize the likelihood of accuracy in a
        particular genre.
        '''

        if agenre in self.genrecounts:
            pagesingenre = self.genrecounts[agenre]
        else:
            pagesingenre = 0

        genreproportion = pagesingenre / self.pagelen

        features = np.zeros(8)

        if agenre == 'fic':

            if 'Fiction' in self.genres or 'Novel' in self.genres or 'Short stories' in self.genres:
                features[0] = 1

            if 'Drama' in self.genres or 'Poetry' in self.genres or self.nonmetaflag:
                features[1] = 1

        if agenre == 'poe':

            if 'Poetry' in self.genres or 'poems' in self.title.lower():
                features[0] = 1

            if 'Drama' in self.genres or 'Fiction' in self.genres or self.nonmetaflag:
                features[1] = 1

        if agenre == 'dra':

            if 'Drama' in self.genres or 'plays' in self.title.lower():
                features[0] = 1

            if 'Fiction' in self.genres or 'Poetry' in self.genres or self.nonmetaflag:
                features[1] = 1

        features[2] = genreproportion
        features[3] = self.rawflipratio
        features[4] = self.smoothflips
        features[5] = self.avggap
        features[6] = self.maxprob
        features[7] = self.maxratio

        return features

    def genreaccuracy(self, checkgenre, correctgenres):
        truepositives = 0
        falsepositives = 0

        for idx, genre in enumerate(self.smoothPredictions):
            if genre == checkgenre:

                if correctgenres[idx] == checkgenre:
                    truepositives += 1
                else:
                    falsepositives += 1

        if (truepositives + falsepositives) > 0:
            precision = truepositives / (truepositives + falsepositives)
        else:
            precision = 1000
            # which we shall agree is a signal that this is meaningless

        return precision

    def match(self, correctgenres):
        assert len(correctgenres) == len(self.smoothPredictions)
        matches = 0
        for idx, genre in enumerate(self.smoothPredictions):
            if correctgenres[idx] == genre:
                matches += 1
            elif correctgenres[idx] == 'bio' and genre == 'non':
                matches += 1
            elif correctgenres[idx] == 'non' and genre == 'bio':
                matches += 1

        return matches / self.pagelen, matches, self.pagelen

    def matchgenres(self, correctgenres):
        poetryTP = 0
        poetryFP = 0
        poetryTN = 0
        poetryFN = 0
        fictionTP = 0
        fictionFP = 0
        fictionTN = 0
        fictionFN = 0

        assert len(correctgenres) == len(self.smoothPredictions)

        for idx, genre in enumerate(self.smoothPredictions):

            if correctgenres[idx] == 'poe':
                if genre == 'poe':
                    poetryTP += 1
                else:
                    poetryFN += 1

            if correctgenres[idx] != 'poe':
                if genre == 'poe':
                    poetryFP += 1
                else:
                    poetryTN += 1

            if correctgenres[idx] == 'fic':
                if genre == 'fic':
                    fictionTP += 1
                else:
                    fictionFN += 1

            if correctgenres[idx] != 'fic':
                if genre == 'fic':
                    fictionFP += 1
                else:
                    fictionTN += 1

        return poetryTP, poetryFP, poetryTN, poetryFN, fictionTP, fictionFP, fictionTN, fictionFN

    def matchvector(self, correctgenres):
        assert len(correctgenres) == len(self.smoothPredictions)
        matches = list()
        for idx, genre in enumerate(self.smoothPredictions):
            if correctgenres[idx] == genre:
                matches.append(1)
            elif correctgenres[idx] == 'bio' and genre == 'non':
                matches.append(1)
            elif correctgenres[idx] == 'non' and genre == 'bio':
                matches.append(1)
            else:
                matches.append(0)

        return matches

def leave1out(xmatrix, yarray, tolparameter = 1):
    ''' Does leave-one-out crossvalidation for a given matrix
    of features and array of y values. Uses regularized
    logistic regression.
    '''
    predictions = np.zeros(len(xmatrix))

    for i in range(0, len(xmatrix)):
        trainingset = pd.concat([xmatrix[0:i], xmatrix[i+1:]])
        trainingacc = yarray[0:i] + yarray[i+1:]
        testset = xmatrix[i: i + 1]
        newmodel = LogisticRegression(C = tolparameter)
        newmodel.fit(trainingset, trainingacc)
        predict = newmodel.predict_proba(testset)[0][1]
        predictions[i] = predict

    featurelist = ['confirm', 'deny', 'thisgenre', 'rawflipratio', 'smoothflips', 'avggap', 'maxprob', 'maxgenre']

    coefficients = list(zip(newmodel.coef_[0], featurelist))
    coefficients.sort()
    for coefficient, word in coefficients:
        print(word + " :  " + str(coefficient))

    print("Leave one out pearson: " + str(pearsonr(yarray, predictions)))

    return predictions

def unpack(predictions, listofmodeledvols):
    ''' This unpacks a list of predictions made on a subset of
    the data, by aligning the predictions with the indexes of
    True values in listofmodeledvols.
    '''
    unpacked = np.zeros(len(listofmodeledvols))
    assert sum(listofmodeledvols) == len(predictions)

    # I.e., there should be as many True values in that list
    # as there are values in predictions.

    ctr = 0
    for idx, wasmodeled in enumerate(listofmodeledvols):
        if wasmodeled:
            unpacked[idx] = predictions[ctr]
            ctr += 1

    return unpacked

# Begin main script.

TOL = 0.1
THRESH = 0.80

genrestocheck = ['fic', 'poe', 'dra']

metadatapath = '/Volumes/TARDIS/work/metadata/MergedMonographs.tsv'
rows, columns, table = utils.readtsv(metadatapath)

firstsource = "/Users/tunder/Dropbox/pagedata/to1923features/genremaps/"
secondsource = "/Users/tunder/Dropbox/pagedata/seventhfeatures/genremaps/"

firstmaps = os.listdir(firstsource)
secondmaps = os.listdir(secondsource)

predictsource = '/Users/tunder/Dropbox/pagedata/production/crosspredicts/'

predicts = os.listdir(predictsource)
predicts = [x for x in predicts if not x.startswith('.')]

allfeatures = list()
accuracies = list()
correctpages = list()
totalpages = list()

poetryTPs = list()
poetryFPs = list()
poetryTNs = list()
poetryFNs = list()
fictionTPs = list()
fictionFPs = list()
fictionTNs = list()
fictionFNs = list()

genrefeatures = dict()
genreprecisions = dict()

modeledvols = dict()

for filename in predicts:
    mapname = filename.replace('.predict', '.map')
    cleanid = utils.pairtreelabel(filename.replace('.predict', ''))

    if mapname in firstmaps:
        firstpath = os.path.join(firstsource, mapname)
        if os.path.isfile(firstpath):
            with open(firstpath, encoding = 'utf-8') as f:
                filelines = f.readlines()
                success = True
        else:
            success = False
    elif mapname in secondmaps:
        secondpath = os.path.join(secondsource, mapname)
        if os.path.isfile(secondpath):
            with open(secondpath, encoding = 'utf-8') as f:
                filelines = f.readlines()
                success = True
        else:
            success = False
    else:
        success = False

    if not success:
        print("Failed to locate a match for " + filename)
        continue
    else:
        correctgenres = list()
        for line in filelines:
            line = line.rstrip()
            fields = line.split('\t')
            literalgenre = fields[1]
            if literalgenre in genretranslations:
                functionalgenre = genretranslations[literalgenre]
            else:
                functionalgenre = literalgenre

            # Necessary because we are not attempting to discriminate all the categories
            # we manually recorded.

            correctgenres.append(functionalgenre)

    filepath = os.path.join(predictsource, filename)
    predicted = Prediction(filepath)

    if cleanid in rows:
        predicted.addmetadata(cleanid, table)
    else:
        print('Missing metadata for ' + cleanid)
        predicted.missingmetadata()

    # matchpercent = predicted.match(correctgenres)
    # allfeatures.append(predicted.getfeatures())
    # accuracies.append(matchpercent)


    proportion, correct, total = predicted.match(correctgenres)
    accuracies.append(proportion)
    correctpages.append(correct)
    totalpages.append(total)
    allfeatures.append(predicted.getfeatures())

    poetryTP, poetryFP, poetryTN, poetryFN, fictionTP, fictionFP, fictionTN, fictionFN = predicted.matchgenres(correctgenres)

    poetryTPs.append(poetryTP)
    poetryFPs.append(poetryFP)
    poetryTNs.append(poetryTN)
    poetryFNs.append(poetryFN)

    fictionTPs.append(fictionTP)
    fictionFPs.append(fictionFP)
    fictionTNs.append(fictionTN)
    fictionFNs.append(fictionFN)

    for genre in genrestocheck:
        precision = predicted.genreaccuracy(genre, correctgenres)
        if precision <= 1:
            utils.appendtodict(genre, predicted.genrefeatures(genre), genrefeatures)
            utils.appendtodict(genre, precision, genreprecisions)
            utils.appendtodict(genre, True, modeledvols)
        else:
            utils.appendtodict(genre, False, modeledvols)
            # Precision > 1 is a signal that we actually have no true or false
            # positives in the volume for this genre. In that circumstance, we're
            # not going to use the volume to train a metamodel for the genre, because
            # it won't usefully guide what we want to guide -- assessment of the
            # accuracy of our positive predictions for this genre.
            #
            # So we don't append the genre features or precision to the arrays
            # that are going to be used to create a genre-specific metamodel.
            #
            # On the other hand, there could be false negatives in the volume, and
            # we want to acknowledge that when calculating overall recall.
            #
            # SO what we do is create a list of "modeledvols" for each genre. Then
            # we can unpack the predictions of the model and distribute them back
            # into a longer array that covers all volumes, with negative
            # predictions for vols that have no

featurearray = np.array(allfeatures)
correctpages = np.array(correctpages)
totalpages = np.array(totalpages)

poetryTPs = np.array(poetryTPs)
poetryFPs = np.array(poetryFPs)
poetryTNs = np.array(poetryTNs)
poetryFNs = np.array(poetryFNs)

fictionTPs = np.array(fictionTPs)
fictionFPs = np.array(fictionFPs)
fictionTNs = np.array(fictionTNs)
fictionFNs = np.array(fictionFNs)

# We also need to unpack the versions of these arrays that are keyed to the special models
# created for poetry and fiction volumes. (We need different versions because these models
# will have a different length, since they only contain files)

# Now let's normalize features by centering on mean and scaling
# by standard deviation

featurearray = normalizearray(featurearray)

data = pd.DataFrame(featurearray)

binarized = binarize(accuracies, threshold = THRESH)

logisticmodel = LogisticRegression(C = TOL)
logisticmodel.fit(data, binarized)

featurelist = ['confirmfic', 'denyfic', 'confirmpoe', 'denypoe', 'confirmdra', 'denydra', 'confirmnon', 'denynon', 'maxratio', 'rawflipratio', 'smoothflips', 'avggap', 'maxprob']

# featurelist = ['maxratio', 'rawflipratio', 'smoothflips', 'avggap', 'maxprob']

coefficients = list(zip(logisticmodel.coef_[0], featurelist))
coefficients.sort()
for coefficient, word in coefficients:
    print(word + " :  " + str(coefficient))

selfpredictions = logisticmodel.predict_proba(data)[ : , 1]
print("Pearson for whole data: ")
print(pearsonr(accuracies, selfpredictions))

predictions = np.zeros(len(data))

for i in range(0, len(data)):
    trainingset = pd.concat([data[0:i], data[i+1:]])
    trainingacc = binarized[0:i] + binarized[i+1:]
    testset = data[i: i + 1]
    newmodel = LogisticRegression(C = TOL)
    newmodel.fit(trainingset, trainingacc)

    predict = newmodel.predict_proba(testset)[0][1]
    predictions[i] = predict

print()
print('Pearson for test set:' )
print(pearsonr(predictions, accuracies))

genrepredictions = dict()
unpackedpredictions = dict()

for genre in genrestocheck:
    print(genre)
    genrearray = np.array(genrefeatures[genre])
    genrearray = normalizearray(genrearray)
    gdata = pd.DataFrame(genrearray)
    numinstances, numfeatures = gdata.shape

    gbinary = binarize(genreprecisions[genre], threshold= THRESH)
    genrepredictions[genre] = leave1out(gdata, gbinary, tolparameter = TOL)
    unpackedpredictions[genre] = unpack(genrepredictions[genre], modeledvols[genre])

def testtwo(aseq, bseq, thresh):
    bothfail = 0
    afail = 0
    bfail = 0
    c = 0
    assert len(aseq) == len(bseq)
    for a,b in zip(aseq, bseq):
        if a < thresh and b< thresh:
            c += 1
            bothfail += 1
        elif a > thresh and b > thresh:
            c += 1
        elif a < thresh and b > thresh:
            afail += 1
        elif a > thresh and b < thresh:
            bfail += 1
        else:
            print('whoa')
            pass

    return c / len(aseq), afail, bfail, bothfail

def corpusaccuracy(predictions, correctpages, totalpages, threshold):
    allcorrect = np.sum(correctpages[predictions > threshold])
    alltotal = np.sum(totalpages[predictions > threshold])
    return allcorrect / alltotal

def corpusrecall(predictions, correctpages, totalpages, threshold):
    missedcorrect = np.sum(correctpages[predictions < threshold])
    correcttotal = np.sum(correctpages)
    return missedcorrect / correcttotal

def precision(genreTP, genreFP, genreTN, genreFN, predictions, threshold):
    truepos = np.sum(genreTP[predictions>threshold])
    falsepos = np.sum(genreFP[predictions>threshold])

    precision = truepos / (truepos + falsepos)

    falsenegs = np.sum(genreFN[predictions >= threshold])
    missedpos = np.sum(genreTP[predictions < threshold])
    missednegs = np.sum(genreFN[predictions < threshold])

    totalfalsenegs = falsenegs + missedpos + missednegs

    # Because the threshold also cuts things off.

    recall = truepos / (truepos + totalfalsenegs)

    return precision, recall


#plotresults
import matplotlib.pyplot as plt
precisions = list()
recalls= list()
for T in range(100):
    tr = T / 100
    p, r = precision(fictionTPs, fictionFPs, fictionTNs, fictionFNs, unpackedpredictions['fic'], tr)
    precisions.append(p)
    recalls.append(r)

poeprecisions = list()
poerecalls= list()
for T in range(100):
    tr = T / 100
    p, r = precision(poetryTPs, poetryFPs, poetryTNs, poetryFNs, unpackedpredictions['poe'], tr)
    poeprecisions.append(p)
    poerecalls.append(r)

import csv

with open('/Users/tunder/output/confidence80.csv', mode = 'w', encoding='utf-8') as f:
    writer = csv.writer(f)
    row = ['ficprecision', 'ficrecall', 'poeprecision', 'poerecall']
    writer.writerow(row)
    for idx in range(100):
        row = [precisions[idx], recalls[idx], poeprecisions[idx], poerecalls[idx]]
        writer.writerow(row)
