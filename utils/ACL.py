#!/usr/bin/env python
import logging
from utils.Shell  import *
from utils.Common import getMyLogger

ROLE_ADMIN       = 'admin'
ROLE_CONTRIBUTOR = 'contributor'
ROLE_USER        = 'user'

ROLE_ACL         = { ROLE_ADMIN       : 'RXWdDoy',
                     ROLE_CONTRIBUTOR : 'rwaDdxnNtTcy',
                     ROLE_USER        : 'RXy' }
   
def get_permission(role):
    ''' gets permission bits for DENY and ALLOW, given the role
    '''
    all_permission = 'rwaDdxnNtTcCoy'

    _alias_ = { 'R': 'rntcy',
                'W': 'watTNcCy',
                'X': 'xtcy' }
 
    acl = {} 
    try:
        _acl_a = ROLE_ACL[role]

        for k,v in _alias_.iteritems():
            _acl_a = _acl_a.replace(k, v)

        _acl_a = ''.join( list( set(list(_acl_a)) ) )
        _acl_d = ''.join( list( set(list(all_permission)) - set(list(_acl_a)) ) )

        acl['A'] = _acl_a
        acl['D'] = _acl_d

    except KeyError,e:
        logger.error('No such role: %s' % role)

    return acl

def getRoleFromACE(ace, lvl=0):
    ''' converts ACE permission into the defined roles: admin, user, contributor
    '''

    logger = getMyLogger(lvl=lvl)

    diff = {}
    for r in [ROLE_ADMIN, ROLE_CONTRIBUTOR, ROLE_USER]:
        diff[r] = list( set(list(ace)) ^ set(list( get_permission(r)['A']  )) )
        logger.debug('diff to role %s: %s' % (r, repr(diff[r])))

    ## find the closest match, i.e. shortest string on the value of the diff dict
    return sorted(diff.items(), key=lambda x:len(x[1]))[0][0]

def delACE(path, users, roles=None, lvl=0):
    ''' deletes all ACE entry related to the given list of users.
        If roles are gien, only the ACEs corresponding to the roles are deleted.
    '''

    logger = getMyLogger(lvl=lvl)

    if not users:
        return True

    if not roles:
        roles = [ROLE_ADMIN, ROLE_CONTRIBUTOR, ROLE_USER]

    _acls_perm = {}
    for r in roles:
        _acls_perm[r] = get_permission(r)

    _acl  = []
    _opts = ['-R','-x']
    for u in users:
        for r,p in _acls_perm.iteritems():

            #if u == os.environ['LOGNAME'] and r == 'admin':
            #    logger.warn('skip removing %s from admin role.' % u)
            #    continue

            _acl.append('D:fd:%s@dccn.nl:%s' % (u, p['D'])) 
            _acl.append('A:fd:%s@dccn.nl:%s' % (u, p['A']))

            ## add possible variations when permissions are propogate to files
            _acl.append('D::%s@dccn.nl:%s' % (u, p['D'].replace('D',''))) 
            _acl.append('A::%s@dccn.nl:%s' % (u, p['A'].replace('D','')))

    for a in _acl:
        logger.debug('delete ACE: %s' % a) 

    return __nfs4_setfacl__(path, _acl, _opts)

def getACE(path, user=None, recursive=False, lvl=0):
    ''' gets ACEs for given user or for all ACEs if user is not given. 
    '''

    logger = getMyLogger(lvl=lvl)

    def __nfs4_getfacl__(fpath):

        logger.debug('get ACL of %s ...' % fpath)

        ## workaround for NetApp for the path is actually the root of the volume
        if fpath[-1] is not '/':
            fpath += '/'

        cmd = 'nfs4_getfacl %s' % fpath 
        rc, output, m = s.cmd1(cmd, allowed_exit=[0,255], timeout=None)
        if rc != 0:
            logger.error('%s failed' % cmd)
            return None
        else:
            return __parseACLStr__(output)
        
    acl = {}
    s   = Shell()
    if recursive:
        ## walk through all directories/files under the path
        for r,ds,fs in os.walk(path,onerror=__fs_walk_error__):
            ## retrieve directory ACL
            acl[r] = __nfs4_getfacl__(r)
 
            ## retrieve file ACL
            for f in map(lambda x:os.path.join(r,x), fs):
                acl[f] = __nfs4_getfacl__(f)
    else:
        acl[path] = __nfs4_getfacl__(path)

    return acl

def setACE(path, users=[], contributors=[], admins=[], lvl=0):
    ''' adds/sets ACEs for user, contributor and admin roles.
         - for user id not presented in current ACL, create a new ACE.
         - for user id already presented in current ACL, update it by
           removing followed by adding it back with correct right.
    '''

    logger = getMyLogger(lvl=lvl)

    ## firstly check if same user id appears in three input lists.
    ## if so, an error is thrown.
    common = list( set(users) & set(contributors) & set(admins) )

    if common:
        for u in common:
            logger.error('user %s presents in multiple roles.' % u)
        return False

    ## retrieve current ACEs of the top directory to check which users 
    ## are presented in the current ACEs
    _ulist_a = users + contributors + admins

    ## if the entire user list is empty, just return true
    if not _ulist_a:
        return True

    _ulist_e = []
    aces = getACE(path, recursive=False, lvl=lvl)[path]
    for a in aces:
        u = a[2].split('@')[0]
        if u in _ulist_a:
            _ulist_e.append(u)

    _ulist_e = list(set(_ulist_e))

    if not delACE(path, _ulist_e, lvl=lvl):
        logger.error('Unable to remove existing ACEs of users: %s' % ', '.join(_ulist_e) )
        return False

    ulist = {'user':users, 'contributor':contributors, 'admin':admins}
    aces  = []
    opts  = ['-R', '-a']
    for k,v in ulist.iteritems():
        logger.info('Setting %s permission ...' % k)
        _perm = get_permission(k)
        for u in v:
            aces.append('D:fd:%s@dccn.nl:%s' % (u, _perm['D']))
            aces.append('A:fd:%s@dccn.nl:%s' % (u, _perm['A']))

    for a in aces:
        logger.debug('add ACE: %s' % a)

    return __nfs4_setfacl__(path, aces, opts)

def __nfs4_setfacl__(fpath, aces, options=None):
    ''' wrapper for calling nfs4_setfacl command.
         - fpath  : the path the ACEs will be applied
         - aces   : the ACEs in a list of strings
         - options: the command-line options in a list of strings 
    '''
    if options:
        cmd = 'nfs4_setfacl %s ' % ' '.join(options)
    else:
        cmd = 'nfs4_setfacl '

    ## workaround for NetApp for the path is actually the root of the volume
    if fpath[-1] is not '/':
        fpath += '/'

    cmd += '"%s" %s' % ( ', '.join(aces), fpath )

    s = Shell()
    rc, output, m = s.cmd1(cmd, allowed_exit=[0,255], timeout=None)
    if rc != 0:
        logger.error('%s failed' % cmd)
        return False 
    else:
        return True
   
def __fs_walk_error__(err):
    ''' handles error if not able to perform listdir on a file.
    '''
    print 'cannot list file: %s' % err.filename

def __parseACLStr__(acl_str):
    ''' splits ACL into ACEs and parse each ACEs into a tuple of (type,flag,principle,permission) 
    '''
    acl = [] 
    for ace in acl_str.split('\n'):
        if ace:
            acl.append(ace.split(':'))

    return acl
