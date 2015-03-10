#!/usr/bin/env python
import os
import pickle
import pwd
import datetime
import socket
from utils.acl.ACE import ACE
from utils.acl.ProjectACL import ProjectACL
from utils.Shell import Shell
from utils.acl.UserRole import ROLE_ADMIN, ROLE_CONTRIBUTOR, ROLE_TRAVERSE, ROLE_USER
from utils.acl.Logger import getLogger


class Nfs4ProjectACL(ProjectACL):

    def __init__(self, project_root, lvl=0):
        ProjectACL.__init__(self, project_root, lvl)
        self.type = 'NFS4'

        self.ROLE_PERMISSION = {ROLE_ADMIN: 'RXWdDoy',
                                ROLE_CONTRIBUTOR: 'rwaDdxnNtTcy',
                                ROLE_USER: 'RXy',
                                ROLE_TRAVERSE: 'x'}

        self.all_permission = 'rwaDdxnNtTcCoy'

        self._alias_ = {'R': 'rntcy',
                        'W': 'watTNcCy',
                        'X': 'xtcy'}

        self.default_principles = ['GROUP', 'OWNER', 'EVERYONE']

    def getRoles(self, path='', recursive=False):

        path = os.path.join(self.project_root, path)

        def __fs_walk_error__(err):
            print 'cannot list file: %s' % err.filename

        # make system call to retrieve NFSV4 ACL
        acl = {}
        if recursive:
            # walk through all directories/files under the path
            for r, ds, fs in os.walk(path, onerror=__fs_walk_error__):
                # retrieve directory ACL
                acl[r] = self.__nfs4_getfacl__(r)

                # retrieve file ACL
                for f in map(lambda x: os.path.join(r, x), fs):
                    acl[f] = self.__nfs4_getfacl__(f)
        else:
            acl[path] = self.__nfs4_getfacl__(path)

        # convert NFSV4 ACL into roles
        roles = {}
        for p, aces in acl.iteritems():

            # initialize role_data for the path 'p'
            r_data = {}
            for r in self.ROLE_PERMISSION.keys():
                r_data[r] = []

            for ace in aces:
                # exclude the default principles
                u = ace.principle.split('@')[0]
                if u not in self.default_principles and ace.type in ['A']:
                    r = self.mapACEtoRole(ace)
                    r_data[r].append(u)
                    self.logger.debug('user %s: permission %s, role %s' % (u, ace.mask, r))

            roles[p] = r_data

        return roles

    def mapRoleToACE(self, role):
        pass

    def setRoles(self, path='', users=[], contributors=[], admins=[], recursive=True, force=False, traverse=False):

        path = os.path.join(self.project_root, path)

        # stop role setting if the same user id appears in multiple user lists
        common = list( set(users) & set(contributors) & set(admins) )

        if common:
            for u in common:
                self.logger.error('user %s presents in multiple roles.' % u)
            return False

        ulist = {ROLE_ADMIN: admins,
                 ROLE_CONTRIBUTOR: contributors,
                 ROLE_USER: users}

        # get current ACEs on the path
        o_aces = self.__nfs4_getfacl__(path)[path]

        if not force:
            # check user roles in existing ACL to avoid redundant operations
            for ace in o_aces:

                u = ace.principle.split('@')[0]

                if u not in self.default_principles and ace.type in ['A']:
                    r = self.mapACEtoRole(ace)
                    if u in ulist[r]:
                        self.logger.warning("skip redundant role setting: %s -> %s" % (u,r))
                        ulist[r].remove(u)

        # if the entire user list is empty, just return true
        _ulist_a = users + contributors + admins
        if not _ulist_a:
            self.logger.warning("I have nothing to do!")
            return True

        # TODO: making sure users in _ulist_a have traverse permission if for parent directories.

        # compose new ACL based on the existing ACL
        n_aces = []
        for ace in o_aces:
            u = ace.principle.split('@')[0]
            if u not in _ulist_a:
                n_aces.append(ace)

        # prepending ACEs related to the given user list
        opts = ['-R', '-s']
        for k, v in ulist.iteritems():
            self.logger.info('setting %s permission ...' % k)
            _perm = self.__get_permission__(k)
            for u in v:
                n_aces.insert(0, ACE(type='A', flag='fd', principle='%s@dccn.nl' % u, mask='%s' % _perm['A']))

        return self.__nfs4_setfacl__(path, n_aces, opts)

    def delUser(self, path='', users=[]):
        path = os.path.join(self.project_root, path)
        pass

    def mapACEtoRole(self, ace):
        diff = {}
        for r in self.ROLE_PERMISSION.keys():
            diff[r] = list(set(list(ace.mask)) ^ set(list(self.__get_permission__(r)['A'])))
            self.logger.debug('diff to role %s: %s' % (r, repr(diff[r])))

        # find the closest match, i.e. shortest string on the value of the diff dict
        return sorted(diff.items(), key=lambda x: len(x[1]))[0][0]

    # internal functions
    def __get_permission__(self, role):
        """
        gets ACE's permission mask for DENY and ALLOW types wrt the given role
        :param role: the role
        :return: an permission mask dictionary with keys 'A' and 'D' corresponding to the ALLOW and DENY types
        """

        ace = {}
        try:
            _ace_a = self.ROLE_PERMISSION[role]

            for k, v in self._alias_.iteritems():
                _ace_a = _ace_a.replace(k, v)

            _ace_a = ''.join(list(set(list(_ace_a))))
            _ace_d = ''.join(list(set(list(self.all_permission)) - set(list(_ace_a))))

            ace['A'] = _ace_a
            ace['D'] = _ace_d

        except KeyError, e:
            self.logger.error('No such role: %s' % role)

        return ace

    def __nfs4_getfacl__(self, path):

        self.logger.debug('get ACL of %s ...' % path)

        def __parseACL__(acl_str):
            """ parses ACL table into ACE objects
            """
            acl = []
            for ace in acl_str.split('\n'):
                if ace:
                    d = ace.split(':')
                    acl.append(ACE(type=d[0], flag=d[1], principle=d[2], mask=d[3]))
            return acl

        # workaround for NetApp for the path is actually the root of the volume
        if os.path.isdir(path) and path[-1] is not '/':
            path += '/'

        cmd = 'nfs4_getfacl %s' % path
        s = Shell()
        rc, output, m = s.cmd1(cmd, allowed_exit=[0, 255], timeout=None)
        if rc != 0:
            self.logger.error('%s failed' % cmd)
            return None
        else:
            return __parseACL__(output)

    def __userExist__(self, uid):
        """
        checks if given user id is existing as a valid system user id

        :param uid: the system user id
        :return: True if the uid is valid, otherwise False
        """

        ick = False
        try:
            pwd.getpwnam(uid)
            ick = True
        except KeyError, e:
            pass
        return ick

    def __curateACE__(self, aces):
        """
        curate given ACEs with the following things:
             - make the ACEs for USER, GROUP and EVERYONE always inherited, making Windows friendly
             - remove ACEs associated with an invalid system account
        :param aces: a list of ACE objects to be scan through
        :return: a list of curated ACE objects
        """

        n_aces = []
        for ace in aces:
            u = ace.principle.split('@')[0]
            if u in self.default_principles:
                # to make it general: remove 'f' and 'd' bits and re-prepend them again
                ace.flag = 'fd%s' % ace.flag.replace('f', '').replace('d', '')
                n_aces.append(ace)
            elif self.__userExist__(u):
                n_aces.append(ace)
            else:
                self.logger.warning('ignore ACE for invalid user: %s' % u)

        return n_aces

    def __nfs4_setfacl__(self, path, aces, options=None):
        """
        wrapper for calling nfs4_setfacl command.
        :param path: the path on which the given ACEs will be applied
        :param aces: a list of ACE objects
        :param options: command-line options for nfs4_setfacl command
        :return: True if the operation succeed, otherwiser False
        """

        aces = self.__curateACE__(aces)

        self.logger.debug('***** new ACL to set *****')
        for a in aces:
            self.logger.debug(a)

        if options:
            cmd = 'nfs4_setfacl %s ' % ' '.join(options)
        else:
            cmd = 'nfs4_setfacl '

        # workaround for NetApp for the path is actually the root of the volume
        if os.path.isdir(path) and path[-1] is not '/':
            path += '/'

        # check existance of the .setacl_lock file in the project's top directory
        lock_fpath = os.path.join(self.project_root, '.setacl_lock')
        if os.path.exists(lock_fpath):
            self.logger.error('cannot setacl as lock file \'%s\' has been acquired by other process' % lock_fpath)
            return False

        # serialize client information in to the .setacl_lock file
        f = open(lock_fpath, 'wb')
        pickle.dump({'time': datetime.datetime.now(),
                     'ip': socket.gethostbyname(socket.gethostname()),
                     'uid': os.getlogin(),
                     'aces': aces}, f)
        f.close()

        cmd += '"%s" %s' % (', '.join(str(aces)), path)

        s = Shell()
        rc, output, m = s.cmd1(cmd, allowed_exit=[0,255], timeout=None)
        if rc != 0:
            self.logger.error('%s failed' % cmd)

        # cleanup lock file regardless the result
        try:
            os.remove(lock_fpath)
        except:
            pass

        return not rc
