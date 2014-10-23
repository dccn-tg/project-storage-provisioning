#!/bin/env python
import sys
import os 
import logging
from argparse import ArgumentParser

## adding PYTHONPATH for access to utility modules and 3rd-party libraries
sys.path.append(os.path.dirname(os.path.abspath(__file__))+'/external/lib/python')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.ACL    import getACE, setACE, delACE, getRoleFromACE, ROLE_ACL
from utils.Common import getMyLogger, csvArgsToList

## set default logger format
logging.basicConfig(format='[%(levelname)s:%(name)s] %(message)s')

## execute the main program
if __name__ == "__main__":

    parg = ArgumentParser(description='delete user\'s access right to project storage', version="0.1")

    ## positional arguments
    parg.add_argument('ulist',
                      metavar = 'ulist',
                      nargs   = 1,
                      help    = 'a list of the system user id separated by ","')

    parg.add_argument('pid',
                      metavar = 'pid',
                      nargs   = '+',
                      help    = 'the project id')

    ## optional arguments
    parg.add_argument('-l','--loglevel',
                      action  = 'store',
                      dest    = 'verbose',
                      type    = int,
                      choices = [0, 1, 2, 3],
                      default = 0,
                      help    = 'set the verbosity level, 0:WARNING, 1:ERROR, 2:INFO, 3:DEBUG (default: %(default)s)')

    parg.add_argument('-d','--basedir',
                      action  = 'store',
                      dest    = 'basedir',
                      default = '/project',
                      help    = 'set the basedir in which the project storages are located (default: %(default)s)')

    args = parg.parse_args()

    _l_user = csvArgsToList(args.ulist[0].strip())

    ## It does not make sense to remove myself from project ...
    me = os.environ['LOGNAME']
    try:
        _l_user.remove( me )
    except ValueError, e:
        pass

    logger = getMyLogger(name=__file__, lvl=args.verbose)

    for id in args.pid:
        p = os.path.join(args.basedir, id)
        if os.path.exists(p):
            if not delACE(p, _l_user, lvl=args.verbose):
                logger.error('fail to remove %s from project %s.' % (','.join(_l_user), id))
            else:
                logger.info('remove %s from project %s.' % (','.join(_l_user), id))
