#!/usr/bin/python2.7
#
# corenlp  - Python interface to Stanford Core NLP tools
# Copyright (c) 2012 Dustin Smith
#   https://github.com/dasmith/stanford-corenlp-python
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

#Modified for use at Zynga by Suryaveer Lodha (2013)

import json, optparse, os, re, sys, time, traceback
import jsonrpc, pexpect
from progressbar import ProgressBar, Fraction
from unidecode import unidecode
import nltk, json, inspect
from nltk import tokenize as tk
from nltk.tree import Tree
import nltk.data
from simplejson import loads
from jsonrpc import ServerProxy, JsonRpc20, TransportTcpIp

STATE_START, STATE_TEXT, STATE_WORDS, STATE_TREE, STATE_DEPENDENCY, STATE_COREFERENCE = 0, 1, 2, 3, 4, 5
WORD_PATTERN = re.compile('\[([^\]]+)\]')
CR_PATTERN = re.compile(r"\((\d*),(\d)*,\[(\d*),(\d*)\)\) -> \((\d*),(\d)*,\[(\d*),(\d*)\)\), that is: \"(.*)\" -> \"(.*)\"")
tokenizer = nltk.data.load('file:english.pickle')


def remove_id(word):
    """Removes the numeric suffix from the parsed recognized words: e.g. 'word-2' > 'word' """
    return word.count("-") == 0 and word or word[0:word.rindex("-")]


def parse_bracketed(s):
    '''Parse word features [abc=... def = ...]
    Also manages to parse out features that have XML within them
    '''
    word = None
    attrs = {}
    temp = {}
    # Substitute XML tags, to replace them later
    for i, tag in enumerate(re.findall(r"(<[^<>]+>.*<\/[^<>]+>)", s)):
        temp["^^^%d^^^" % i] = tag
        s = s.replace(tag, "^^^%d^^^" % i)
    # Load key-value pairs, substituting as necessary
    for attr, val in re.findall(r"([^=\s]*)=([^=\s]*)", s):
        if val in temp:
            val = temp[val]
        if attr == 'Text':
            word = val
        else:
            attrs[attr] = val
    return (word, attrs)


def parse_parser_results(text):
    """ This is the nasty bit of code to interact with the command-line
    interface of the CoreNLP tools.  Takes a string of the parser results
    and then returns a Python list of dictionaries, one for each parsed
    sentence.
    """
    results = {"sentences": []}
    state = STATE_START
    for line in unidecode(text).split("\n"):
        line = line.strip()
        
        if line.startswith("Sentence #"):
            sentence = {'words':[], 'parsetree':[], 'dependencies':[]}
            results["sentences"].append(sentence)
            state = STATE_TEXT
        
        elif state == STATE_TEXT:
            sentence['text'] = line
            state = STATE_WORDS
        
        elif state == STATE_WORDS:
            if not line.startswith("[Text="):
                raise Exception('Parse error. Could not find "[Text=" in: %s' % line)
            for s in WORD_PATTERN.findall(line):
                sentence['words'].append(parse_bracketed(s))
            state = STATE_TREE
        
        elif state == STATE_TREE:
            if len(line) == 0:
                state = STATE_DEPENDENCY
                sentence['parsetree'] = " ".join(sentence['parsetree'])
            else:
                sentence['parsetree'].append(line)
        
        elif state == STATE_DEPENDENCY:
            if len(line) == 0:
                state = STATE_COREFERENCE
            else:
                split_entry = re.split("\(|, ", line[:-1])
                if len(split_entry) == 3:
                    rel, left, right = map(lambda x: remove_id(x), split_entry)
                    sentence['dependencies'].append(tuple([rel,left,right]))
        
        elif state == STATE_COREFERENCE:
            if "Coreference set" in line:
                if 'coref' not in results:
                    results['coref'] = []
                coref_set = []
                results['coref'].append(coref_set)
            else:
                for src_i, src_pos, src_l, src_r, sink_i, sink_pos, sink_l, sink_r, src_word, sink_word in CR_PATTERN.findall(line):
                    src_i, src_pos, src_l, src_r = int(src_i)-1, int(src_pos)-1, int(src_l)-1, int(src_r)-1
                    sink_i, sink_pos, sink_l, sink_r = int(sink_i)-1, int(sink_pos)-1, int(sink_l)-1, int(sink_r)-1
                    coref_set.append(((src_word, src_i, src_pos, src_l, src_r), (sink_word, sink_i, sink_pos, sink_l, sink_r)))
    
    return results


class StanfordCoreNLP(object):
    """
    Command-line interaction with Stanford's CoreNLP java utilities.
    Can be run as a JSON-RPC server or imported as a module.
    """
    def __init__(self):
        """
        Checks the location of the jar files.
        Spawns the server as a process.
        """
        jars = ["stanford-corenlp-2012-07-09.jar",
                "stanford-corenlp-2012-07-06-models.jar",
                "joda-time.jar",
                "xom.jar"]
       
        # if CoreNLP libraries are in a different directory,
        # change the corenlp_path variable to point to them
        corenlp_path = "stanford-corenlp-2012-07-09/"
        
        java_path = "java"
        classname = "edu.stanford.nlp.pipeline.StanfordCoreNLP"
        # include the properties file, so you can change defaults
        # but any changes in output format will break parse_parser_results()
        props = "-props default.properties" 
        
        # add and check classpaths
        jars = [corenlp_path + jar for jar in jars]
        for jar in jars:
            if not os.path.exists(jar):
                print "Error! Cannot locate %s" % jar
                sys.exit(1)
        
        # spawn the server
        start_corenlp = "%s -Xmx1800m -cp %s %s %s" % (java_path, ':'.join(jars), classname, props)
        print start_corenlp
        self.corenlp = pexpect.spawn(start_corenlp)
        
        # show progress bar while loading the models
        widgets = ['Loading Models: ', Fraction()]
        pbar = ProgressBar(widgets=widgets, maxval=5, force_update=True).start()
        self.corenlp.expect("done.", timeout=20) # Load pos tagger model (~5sec)
        pbar.update(1)
        self.corenlp.expect("done.", timeout=200) # Load NER-all classifier (~33sec)
        pbar.update(2)
        self.corenlp.expect("done.", timeout=600) # Load NER-muc classifier (~60sec)
        pbar.update(3)
        self.corenlp.expect("done.", timeout=600) # Load CoNLL classifier (~50sec)
        pbar.update(4)
        self.corenlp.expect("done.", timeout=200) # Loading PCFG (~3sec)
        pbar.update(5)
        self.corenlp.expect("Entering interactive shell.")
        pbar.finish()
    
    def _parse(self, text):
        """
        This is the core interaction with the parser.
        
        It returns a Python data-structure, while the parse()
        function returns a JSON object
        """
        # clean up anything leftover
        while True:
            try:
                self.corenlp.read_nonblocking (4000, 0.3)
            except pexpect.TIMEOUT:
                break
        
        self.corenlp.sendline(text)
        
        # How much time should we give the parser to parse it?
        # the idea here is that you increase the timeout as a 
        # function of the text's length.
        # anything longer than 5 seconds requires that you also
        # increase timeout=5 in jsonrpc.py
        max_expected_time = min(5, 3 + len(text) / 20.0)
        end_time = time.time() + max_expected_time
        
        incoming = ""
        while True:
            # Time left, read more data
            try:
                incoming += self.corenlp.read_nonblocking(2000, 1)
                if "\nNLP>" in incoming: break
                time.sleep(0.0001)
            except pexpect.TIMEOUT:
                if end_time - time.time() < 0:
                    print "[ERROR] Timeout"
                    return {'error': "timed out after %f seconds" % max_expected_time,
                            'input': text,
                            'output': incoming}
                else:
                    continue
            except pexpect.EOF:
                break
        
        try:
            results = parse_parser_results(incoming)
        except Exception, e:
            raise e
        
        return results
    
    def parse(self, text):
        """ 
        This function takes a text string, sends it to the Stanford parser,
        reads in the result, parses the results and returns a list
        with one dictionary entry for each parsed sentence, in JSON format.
        """
        return json.loads(json.dumps(self._parse(text)))
    
    def segment(self,line):
        # Use the natural nltk Punkt tokenizer to choose where to segment, then break on 
        # bullet points (u"\u2022")
        line = tokenizer.tokenize(line.strip(), realign_boundaries=True)
        allSegments = []
        for i in range(len(line)):
            bulletSplits = line[i].split(u"\u2022")
            for j in range(len(bulletSplits)):
                if j > 0:
                    bulletSplits[j] = u"\u2022" + bulletSplits[j]
            allSegments = allSegments + bulletSplits
        return allSegments
        
    def exploreSubTree(self,subtree):
        # This is a text node, no more subtrees
        if not isinstance(subtree[0], Tree):
            return 0
        # If there's an ambiguous noun phrase - except for DT no and PRP you
        if subtree.node == "NP" and len(subtree) == 1 and \
            (subtree[0].node == "CD" or (subtree[0].node == "DT" and subtree[0][0].lower() != "no") or \
            (subtree[0].node == "PRP" and (subtree[0][0].lower() != "you" and subtree[0][0].lower() != "we"))):
            print '\t\t\t'+subtree[0][0], subtree[0].node
            return 1
            
        if subtree.node == "NP" and len (subtree) == 2 and not isinstance(subtree[0][0], Tree) and \
            not isinstance(subtree[1][0], Tree) and subtree[0][0].lower() == "this" and \
            subtree[1][0].lower() == "item":
            return 1
            
        retval = 0
        for child in subtree:
            retval = max(self.exploreSubTree(child), retval)
        return retval
            
    def findAmbiguities(self,line):    
        result = self.parse(line) 
        
        #if 'coref' in result:
        #    return 1
    
        trees = []
        retval = 0
        for i in range(len(result['sentences'])):
            tree = Tree.parse(result['sentences'][i]['parsetree'])
            trees.append(tree)
            # Since tree[0] is a S
            for subtree in tree:
                retval = max(retval, self.exploreSubTree(subtree))
        return retval
    
    def tokenize(self,phraseRequest):
        result = {}
        try:
            phrases = phraseRequest['request']
        except KeyError:
            return {'status' : 'FAILED', 'reason' :'"request" key not found in the input.'}
        try:
            for key in phrases.keys():
                canSegment = self.findAmbiguities(phrases[key])
                if canSegment == 0:
                    result[key] = self.segment(phrases[key])
                else:
                    result[key] = [phrases[key]]
        except Exception, e:
            errorTrace = traceback.format_exc().strip('\n')
            reason = errorTrace.split('\n')[-1]
            trace = ('\n').join(errorTrace.split('\n')[:-1])
            return {'status' : 'FAILED', 'element' : key, 'reason' : reason, 'trace' : trace}
            
        return {'status' : 'OK', 'result': result}


if __name__ == '__main__':
    """
    The code below starts an JSONRPC server
    """
    parser = optparse.OptionParser(usage="%prog [OPTIONS]")
    parser.add_option('-p', '--port', default='5985',
                      help='Port to serve on (default 5985)')
    parser.add_option('-H', '--host', default='127.0.0.1',
                      help='Host to serve on (default localhost; 0.0.0.0 to make public)')
    options, args = parser.parse_args()
    server = jsonrpc.Server(jsonrpc.JsonRpc20(),
                            jsonrpc.TransportTcpIp(addr=(options.host, int(options.port))))
    
    nlp = StanfordCoreNLP()
    server.register_function(nlp.parse)
    server.register_function(nlp.tokenize)
    
    print 'Serving on http://%s:%s' % (options.host, options.port)
    server.serve()
