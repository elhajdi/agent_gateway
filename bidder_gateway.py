import sys
import shutil
import os
import logging
import pickle
import subprocess

from bottle import Bottle, run, urljoin, HTTPResponse, request

AGENT_CONFIG_SERVER = 'http://127.0.0.1:9986'

# agent pickle file path
pickle_path = '.bidders'

# agent base path
exec_base_path = '/home/nemi/workspace/test/daemon'

# set up logging
logging.basicConfig(filename='bidder_gateway.log',
        format='%(asctime)-15s %(levelname)s %(message)s', 
        level=logging.DEBUG)
logger = logging.getLogger('bidder_gateway')

# create the bottle app so we don't use the global one
app = Bottle()
# initialize bidder map
bidders = {}


def map_and_redirect(uri, name):
    """
        maps the name, sets the uri and raises a redirection
        otherwise returns the json result code
    """
    try :
        # try to map the name to the internal config name     
        location = urljoin(
            AGENT_CONFIG_SERVER, 
            uri % bidders[name]['agent_conf_name'])
    except :
        return  {
                'resultCode'        :    1,
                'resultDescription' :   'unable to map %s' % name
                }
    raise HTTPResponse("", status=302, Location=location)

@app.get('/v1/agents')
def get_agents():
    """
        returns the list of bidders
    """
    return '%s' % bidders.keys()

@app.post('/v1/agents/<name>/config')
@app.get('/v1/agents/<name>/config')
def get_config(name):
    """
        redirects the call to the agent configuration service
        on /v1/agents/<name>/config for the given name
    """
    return map_and_redirect('/v1/agents/%s/config', name)

@app.post('/v1/agents/<name>/heartbeat')
def heartbeat(name):
    """
        redirects the call to the agent configuration service
        on /v1/agents/<name>/heartbeat for the given name
    """
    return map_and_redirect('/v1/agents/%s/heartbeat', name)
    
@app.get('/v1/agents/all')
def get_all():
    """
        redirects the call to the agent configuration service
        on /v1/agents/all
    """     
    location = urljoin(AGENT_CONFIG_SERVER, '/v1/agents/all')
    raise HTTPResponse("", status=302, Location=location)

@app.post('/v1/agents/<name>/start')
def start_bidder(name):
    """
        Starts up a bidder using as the instance parameters
        the arguments passed in the query string 
    """
    global _process_id
    result = {
            'resultCode'        :   0,
            'resultDescription' :   'ok'
    }

    if name in bidders :
        result['resultCode'] = 1
        result['resultDescription'] = 'bidder already started'    
        return result
    else :
        bidders[name] = {}

    # save the executable name and external name
    bidders[name]['bidder_name'] = name
    bidders[name]['executable'] = request.query['executable']  
    # save the params    
    bidders[name]['params'] = {
         k:v for k,v in request.query.iteritems() 
            if k not in ('bidder_name', 'executable') 
    }
    
    logger.info('bringing up bidder %s=%s' % (name, bidders[name]))

    # set the args a list (popen expects them that way)
    arguments = []
    for k,v in bidders[name]['params'].iteritems() :
        arguments.append('-%s' % k)
        arguments.append(v)
    
    exe = [ './%s' % bidders[name]['executable']]
    exe.extend(arguments)
    # bring the process up
    proc = subprocess.Popen(
        exe, 
        cwd=exec_base_path,        
        shell=False, 
        close_fds=True,
        stdout=subprocess.PIPE)
    # wait for the forker process to finish
    proc.wait()
    pid = int(proc.stdout.readline())
    rc = proc.returncode
    if rc :
        del bidders[name]
        result['resultCode'] = 3
        result['resultDescription'] = 'return code is %d' % rc    
        return result

    # save the pid for the new bidder
    bidders[name]['pid']  = pid
   
    # the key stored by the agent configuration service
    # is a concatenation of the bidder name passed and the
    # pid for for process 
    bidders[name]['agent_conf_name'] = \
        '%s_%s' % (bidders[name]['executable'], bidders[name]['pid'])
    logger.info('bidder %s got pid %d' % (name, bidders[name]['pid']))
    
    # great, let's pickle the data
    try :    
        f = open(os.path.join(pickle_path, str(bidders[name]['pid'])), 'wb')    
        pickle.dump(bidders[name], f)
        f.close()
    except :
        result['resultCode'] = 2
        result['resultDescription'] = 'unable to pickle configuration'

    return result
    

@app.post('/v1/agents/<name>/stop')
def stop_bidder(name):
    """
        Stops a running bidder
    """
    result = {
            'resultCode'        :   0,
            'resultDescription' :   'ok'
    }

    if name not in bidders :
        result['resultCode'] = 1
        result['resultDescription'] = 'bidder not running'    
        return result

    logger.info('stopping bidder %s=%s' % (name, bidders[name]))

    pid = bidders[name]['pid']
    try :
        signal = 9
        if 'signal' in request.query :
            signal = int(request.query['signal'])
        os.kill(pid, signal)
        logger.info('signal %d sent to process with pid %d' % (signal, pid))
    except :
        result['resultCode'] = 2
        result['resultDescription'] = 'unable to kill process %s' % pid    
        return result

    logger.info('bidder %s with pid %d stopped' % (name, pid))
    
    # clean up     
    del bidders[name]
    try :
        os.remove(os.path.join(pickle_path, str(pid)))
    except :
        result = {
            'resultCode'        :   4,
            'resultDescription' :   'unable to delete pickled data'
        }    
    return result

if __name__ == '__main__' :
    logger.warning('starting up server')
    # check if the pickle_path exists
    if not os.path.exists(pickle_path):
          os.mkdir(pickle_path)

    # for each pickled process reload the configuration
    for config in os.listdir(pickle_path):
        f = open(os.path.join(pickle_path, config), 'rb')
        c = pickle.load(f)
        bidders[c['bidder_name']] = c
        f.close() 
        logger.warning('loaded bidder %s=%s' % (c['bidder_name'], c))
        
    run(app, host='localhost', port=8080, reloader=True)
    sys.exit(0)

