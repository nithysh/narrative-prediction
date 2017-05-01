import numpy, argparse, timeit, collections, os, sqlite3, cPickle
import theano
import theano.tensor as T
import theano.typed_list
from keras.preprocessing.sequence import pad_sequences

from transformer import *

numpy.set_printoptions(suppress=True)

#theano.config.compute_test_value = 'raise'

rng = numpy.random.RandomState(123)

class PMI_Model(object):

	def __init__(self, dataset_name):
		self.dataset_name = dataset_name
		self.unigram_counts = None
		self.unigram_counts_filename = "unigram_counts.pkl"
		self.lexicon_size = None
		self.bigram_db_name = "bigram_counts.db"
		self.n_bigram_counts = None
		self.n_bigram_counts_filename = "n_bigram_counts.pkl"
		self.train_stories = None
		self.count_window_bigrams = None

		#if not os.path.isfile(self.dataset_name + "/" + self.bigram_counts_db):
		# if train:
		# 	#specify max number of words in stories from which bigrams are computed
		# 	self.count_all_bigrams()

		#self.n_bigram_counts = self.get_n_bigram_counts()

	def count_unigrams(self, stories):
	    word_counts = {}
	    for story in stories:
	        for word in story:
	            if word in word_counts:
	                word_counts[word] += 1
	            else:
	                word_counts[word] = 1

	    if 1 not in word_counts:
	    	word_counts[1] = 1

	    word_counts[0] = 0

	    words = numpy.array(word_counts.keys())
	    self.unigram_counts = numpy.array(word_counts.values(), dtype='int32')
	    self.unigram_counts = self.unigram_counts[words]

	    #compute num words with count >= min_word_frequency
	    #lexicon_size = numpy.sum(counts >= min_freq)

	    #get indices of lexicon words sorted by their count; 
	    #words that occur less often than the frequency threshold will be removed
	    #sorted_word_indices = numpy.argsort(counts)[::-1]

	    #turn counts into unigram probabilities
	    #counts = counts[sorted_word_indices]
	    #total_count = numpy.sum(counts)
	    #count_unknown_word = numpy.sum(counts[lexicon_size:])
	    #p_words = counts[:lexicon_size] * 1.0 / total_count
	    #self.unigram_counts = counts[:lexicon_size]
	    #insert count of unknown word at index 0
	    #self.unigram_counts = numpy.insert(self.unigram_counts, 0, count_unknown_word)
	    #insert slot for padding
	    #self.unigram_counts = numpy.insert(self.unigram_counts, 0, 0)
	    self.lexicon_size = len(self.unigram_counts)
	    self.n_unigram_counts = sum(self.unigram_counts)
	    self.save(obj=self.unigram_counts, filename=self.unigram_counts_filename)
	    print "Saved", self.lexicon_size, "unigram counts to", self.dataset_name + "/" + self.unigram_counts_filename
    

	def init_count_window_bigrams(self, window_size=None, batch_size=None):

		window = T.matrix('window', dtype='int32')
		window.tag.test_value = rng.randint(low=0, high=self.lexicon_size, size=(window_size, 100)).astype('int32')
		window.tag.test_value[1, 10] = -1
		window.tag.test_value[:, 0] = -1
		window.tag.test_value[-1, 1] = -1

		words1 = window[0]
		words2 = window[1:].T

		word_index = T.scalar('word_index', dtype='int32')
		word_index.tag.test_value = 0
		batch_index = T.scalar('batch_index', dtype='int32')
		batch_index.tag.test_value = 0

		#select words in sequence and batch
		window_ = self.train_stories[word_index:word_index + window_size, batch_index:batch_index + batch_size]
		#filter stories with all empty words from this batch
		window_ = window_[:, T.argmin(window_[0] < 0):]

		self.count_window_bigrams = theano.function(inputs=[word_index, batch_index],\
											outputs=[words1, words2],\
											givens={window: window_},\
											on_unused_input='ignore',\
											allow_input_downcast=True)

		
	def count_all_bigrams(self, stories, window_size=25, batch_size=10000):

		n_stories = len(stories)

		#initialize shared stories with random data
		self.train_stories = theano.shared(rng.randint(low=0, high=self.lexicon_size, size=(window_size, n_stories)).astype('int32'), borrow=True)

		self.init_count_window_bigrams(window_size=window_size, batch_size=batch_size)

		start_time = timeit.default_timer()

		n_bigram_counts = 0

		#create list of dicts for storing bigram counts
		bigram_counts = [collections.defaultdict(int) for word in xrange(self.lexicon_size)]

		# for story_index in xrange(0, len(stories), retrieval_size): #10,000,000
			
		#convert train sequences from list of arrays to matrix
		stories = pad_sequences(sequences=stories, padding='post')
		#sort stories
		lengths = numpy.sum(stories > 0, axis=1)
		stories = stories[numpy.argsort(lengths)]
		stories[stories == 0] = -1

		#make sure batch sizes are even
		if n_stories % batch_size != 0:
			padding = int(numpy.ceil((n_stories % batch_size) * 1. / batch_size)) * batch_size - (n_stories % batch_size)
			stories = numpy.append(numpy.ones((padding, stories.shape[-1]), dtype='int32') * -1, stories, axis=0)
			n_stories = len(stories)

		self.train_stories.set_value(stories.T)
		max_story_length = self.train_stories.get_value().shape[0]

		for batch_index in xrange(0, n_stories, batch_size):

			story_length = numpy.sum(self.train_stories.get_value()[:, batch_index + batch_size - 1] > -1)

			for word_index in xrange(story_length):

				words1, words2 = self.count_window_bigrams(word_index, batch_index)

				for word1_index, word1 in enumerate(words1):
					if numpy.any(words2[word1_index] == -1):
						word2_end_index = numpy.argmax(words2[word1_index] == -1)
					else:
						#no empty words in this set
						word2_end_index = words2.shape[1]
					for word2 in words2[word1_index, :word2_end_index]:
						bigram_counts[word1][word2] += 1
						n_bigram_counts += 1


			print "...processed through word %i/%i" % (story_length, max_story_length), "of %i/%i"\
					% (batch_index + batch_size, n_stories), "stories (%.2fm)" % ((timeit.default_timer() - start_time) / 60)


			#check size of bigram counts dict
			bigram_counts_size = sum([len(bigram_counts[word1]) for word1 in xrange(self.lexicon_size)])
			if bigram_counts_size >= 10000000: #200,000,000?
				#save bigrams from this file
				self.save_bigrams(bigram_counts=bigram_counts)
				#n_bigram_counts_ = self.get_n_bigram_counts()
				#assert n_bigram_counts == n_bigram_counts_
				self.save_n_bigrams(n_bigram_counts=n_bigram_counts)
				
				print "Saved", n_bigram_counts, "bigram counts to", self.dataset_name + "/" + self.bigram_db_name

				#reset bigram counts list
				bigram_counts = [collections.defaultdict(int) for word in xrange(self.lexicon_size)]

		#save remaining bigrams
		self.save_bigrams(bigram_counts=bigram_counts)
		self.save_n_bigrams(n_bigram_counts=n_bigram_counts)
		
		print "Saved", n_bigram_counts, "bigram counts to", self.dataset_name + "/" + self.bigram_db_name

	def save_bigrams(self, bigram_counts=None):

		connection = sqlite3.connect(self.dataset_name + "/" + self.bigram_db_name)
		cursor = connection.cursor()

		#need to create bigram counts db if it hasn't been created
		cursor.execute("CREATE TABLE IF NOT EXISTS bigram(\
						word1 INTEGER,\
						word2 INTEGER,\
						count INTEGER DEFAULT 0,\
						PRIMARY KEY (word1, word2))")

		#create an index on count and words
		cursor.execute("CREATE INDEX IF NOT EXISTS count_index ON bigram(count)")
		cursor.execute("CREATE INDEX IF NOT EXISTS word1_index ON bigram(word1)")
		cursor.execute("CREATE INDEX IF NOT EXISTS word2_index ON bigram(word2)")


		#insert current counts into db
		for word1 in xrange(len(bigram_counts)):
			if bigram_counts[word1]:
				#insert words if they don't already exist
				cursor.executemany("INSERT OR IGNORE INTO bigram(word1, word2)\
								VALUES (?, ?)",\
								[(word1, int(word2)) for word2 in bigram_counts[word1]])
				#now update counts
				cursor.executemany("UPDATE bigram\
								SET count = (count + ?)\
								WHERE word1 = ? AND word2 = ?",
								[(bigram_counts[word1][word2], word1, int(word2)) for word2 in bigram_counts[word1]])

			if word1 > 0 and (word1 % 20000) == 0:
				print "Inserted bigram counts for words up to word", word1

		#commit insert
		connection.commit()

		#close connection
		connection.close()

	def save_n_bigrams(self, n_bigram_counts=None):
		'''since querying the bigram db to get the total number of bigram counts is way too slow, just 
		save the number of counts to a file'''
		self.save(obj=n_bigram_counts, filename=self.n_bigram_counts_filename)


	def get_n_bigram_counts(self):

		#load n_bigram_counts.pkl
		n_bigram_counts = self.load(filename=self.n_bigram_counts_filename)

		#return total number of bigram tokens
		return n_bigram_counts

	def get_bigram_count(self, word1=None, word2=None):

		connection = sqlite3.connect(self.dataset_name + "/" + self.bigram_db_name)
		cursor = connection.cursor()

		cursor.execute("SELECT count FROM bigram WHERE word1 = ? AND word2 = ?", (int(word1), int(word2)))
		bigram_count = cursor.fetchone()
		connection.close()
		if not bigram_count:
			#count is 0, but smooth by tiny number so pmi is not NaN
			bigram_count = 1e-10
		else:
			#add one to existing bigram count
			bigram_count = bigram_count[0]

		#return total number of bigram tokens as well as unique bigram types
		return bigram_count

	def compute_pmi(self, word1=None, word2=None):

		word1_count = self.unigram_counts[word1]
		if not word1_count:
			word1_count = 1e-10
		word2_count = self.unigram_counts[word2]
		if not word2_count:
			word2_count = 1e-10

		#get bigram count from db
		bigram_count = self.get_bigram_count(word1, word2)

		pmi = numpy.log(bigram_count) + numpy.log(self.lexicon_size) - numpy.log(word1_count) - numpy.log(word2_count)

		return pmi

	def score(self, sequences=None):
		'''compute total pmi for each ordered pair of words in a pair of sequences - result is score of association between sequence1 and sequence2'''

		if self.unigram_counts is None:
			self.unigram_counts = self.load(self.unigram_counts_filename)
		if not self.lexicon_size:
			self.lexicon_size = len(self.unigram_counts)

		#sequences should be a list of two sequences
		assert len(sequences) == 2

		sequence1 = sequences[0]
		sequence2 = sequences[1]

		sum_pmi = 0
		pmis = []

		for word1 in sequence1:
			for word2 in sequence2:
				#get pmi of these words
				pmi = self.compute_pmi(word1, word2)
				sum_pmi += pmi
				pmis.append(pmi)

		max_pmi = max(pmis)

		#normalize score by length of sequences
		pmi_score = sum_pmi / (len(sequence1) * len(sequence2))
		#pmi_score = max_pmi

		return pmi_score

	def save(self, obj=None, filename=None):

		filepath = self.dataset_name + "/" + filename

		with open(filepath, 'wb') as object_file:
			cPickle.dump(obj, object_file, protocol=cPickle.HIGHEST_PROTOCOL)

		# return filename

	def load(self, filename=None):

		filepath = self.dataset_name + "/" + filename

		with open(filepath, 'rb') as object_file:
			obj = cPickle.load(object_file)

		return obj


def make_pmi(stories, filepath):
    transformer = SequenceTransformer(min_freq=1, verbose=1, 
                                      replace_ents=False, filepath=filepath)
    stories, _, _ = transformer.fit_transform(X=stories)
    #transformer = load_transformer(filepath)
    #stories, _ = transformer.transform(X=stories)
    pmi_model = PMI_Model(dataset_name=filepath)
    pmi_model.count_unigrams(stories)
    pmi_model.count_all_bigrams(stories)
    return pmi_model

def eval_pmi(transformer, model, input_seqs, output_choices):
    scores = []
    index = 0
    input_seqs, output_choices = transformer.transform(X=input_seqs, y_seqs=output_choices)
    for input_seq, choices in zip(input_seqs, output_choices):
    	choice_scores = [model.score(sequences=[input_seq, choice]) for choice in choices]
    	scores.append(choice_scores)
        # choice1_score = model.score(sequences=[input_seq, output_choices[0]])
        # choice2_score = model.score(sequences=[input_seq, output_choices[1]])
        # choice_scores.append([choice1_score, choice2_score])
        index += 1
        if index % 200 == 0:
            print "predicted", index, "inputs"
        #print choice_scores
    scores = numpy.array(scores)
    pred_choices = numpy.argmax(scores, axis=1)
    return scores, pred_choices


# if __name__ == "__main__":

# 	parser = argparse.ArgumentParser()
# 	parser.add_argument('-dataset', help='Specify name of dataset for PMI model.', required=True)
# 	parser.add_argument('-train', help='Specify train flag to create bigram counts file.', default=False, action='store_true', required=False)
# 	#parser.add_argument('-bigram_file', help='Provide name of file to save bigrams to.', required=True)
# 	args = parser.parse_args()

# 	narrative_dataset = Narrative_Dataset(dataset_name=args.dataset)

# 	#drop previous bigram counts file
# 	if args.train and os.path.isfile(narrative_dataset.dataset_name + "/" + narrative_dataset.bigram_counts_db):
# 		overwrite = raw_input("Are you sure you want to overwrite the bigram counts in " + narrative_dataset.dataset_name + "/" + narrative_dataset.bigram_counts_db + "? (y/n) ")
# 		if overwrite.lower() == "y":
# 			#print "Overwriting bigram counts in ", narrative_dataset.dataset_name + "/" + narrative_dataset.bigram_counts_db
# 			#give user time to cancel overwrite
# 			os.remove(narrative_dataset.dataset_name + "/" + narrative_dataset.bigram_counts_db)

# 	#specify limit on story length
# 	pmi_model = PMI_Model(dataset=narrative_dataset, max_retrieval_length=2000, train=args.train)


