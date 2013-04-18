#Python Server to run segmentation service from CMS REST endpoint.

The SegmentService.py is a tornado Web service which hooks into an exsiting server broadcasting at a port.
corenlp is the Natural language processing server which will tokenize the input string into separate segments and return
a dictionary of status and result.

## Usage

We need Python2.7 for everything here.

First launch the corenlp server (This takes 2-3 minutes, default - 127.0.0.1:5985):

    python corenlp.py

Optionally, you can specify a host or port:

    python corenlp.py -H 0.0.0.0 -p 5980

That will run a public JSON-RPC server on port 5980.

Second, we need to setup the SegmentService. It runs on 127.0.0.1:8888 and listens to 127.0.0.1:5985.
    
    python SegmentService.py

Optionally, you can specify the corenlp host or port, if you did so in the first step:

    python SegmentService.py -host=0.0.0.0 -corenlpPort=5980

Also, you can specify the port where you want SegmentService to run (Default: 8888):

    python SegmentService.py -port=8080

## Sample run:

    python corenlp.py
    python SegmentService.py
    #Single String
    curl 127.0.0.1:8888 -d '{"request":{"original":"Hello World. The world is beautiful"}}'
    {
    "status": "OK", 
    "result": {
        "original": [
            "Hello World.", 
            "The world is beautiful"
            ]
        }
    }

    #Multiple strings
    curl 127.0.0.1:8888 -d '{"request":{"original":"Hello World. The world is beautiful","0":"Hello World. The world is awesome","1":"Hello World. The world is amazing"}}'
    {
    "status": "OK", 
    "result": {
        "1": [
            "Hello World.", 
            "The world is amazing"
            ], 
        "0": [
            "Hello World.", 
            "The world is awesome"
            ], 
        "original": [
            "Hello World.", 
            "The world is beautiful"
            ]
        }
    }

# Contact:
    * Suryaveer Lodha (@slodha)
        
