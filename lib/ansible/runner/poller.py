# (c) 2012-2013, Michael DeHaan <michael.dehaan@gmail.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
#

import time

from ansible import errors

class AsyncPoller(object):
    """ Manage asynchronous jobs. """

    def __init__(self, results, runner):
        self.runner = runner

        self.results = { 'contacted': {}, 'dark': {}}
        self.hosts_to_poll = []
        self.completed = False

        # Get job id and which hosts to poll again in the future
        jid = None
        # True to work with & below
        skipped = True
        for (host, res) in results['contacted'].iteritems():
            if res.get('started', False):
                self.hosts_to_poll.append(host)
                jid = res.get('ansible_job_id', None)
            else:
                skipped = skipped & res.get('skipped', False)
                self.results['contacted'][host] = res
        for (host, res) in results['dark'].iteritems():
            self.results['dark'][host] = res

        if not skipped:
            if jid is None:
                raise errors.AnsibleError("unexpected error: unable to determine jid")
            if len(self.hosts_to_poll)==0:
                raise errors.AnsibleError("unexpected error: no hosts to poll")
        self.jid = jid

    def poll(self):
        """ Poll the job status.

            Returns the changes in this iteration."""
        self.runner.module_name = 'async_status'
        self.runner.module_args = "jid=%s" % self.jid
        self.runner.pattern = "*"
        self.runner.background = 0

        self.runner.inventory.restrict_to(self.hosts_to_poll)
        results = self.runner.run()
        self.runner.inventory.lift_restriction()

        hosts = []
        poll_results = { 'contacted': {}, 'dark': {}, 'polled': {}}
        for (host, res) in results['contacted'].iteritems():
            if res.get('started',False):
                hosts.append(host)
                poll_results['polled'][host] = res
            else:
                self.results['contacted'][host] = res
                poll_results['contacted'][host] = res
                if res.get('failed', False) or res.get('rc', 0) != 0:
                    self.runner.callbacks.on_async_failed(host, res, self.jid)
                else:
                    self.runner.callbacks.on_async_ok(host, res, self.jid)
        for (host, res) in results['dark'].iteritems():
            self.results['dark'][host] = res
            poll_results['dark'][host] = res
            self.runner.callbacks.on_async_failed(host, res, self.jid)

        self.hosts_to_poll = hosts
        if len(hosts)==0:
            self.completed = True

        return poll_results

    def wait(self, seconds, poll_interval):
        """ Wait a certain time for job completion, check status every poll_interval. """
        # jid is None when all hosts were skipped
        if self.jid is None:
            return self.results

        clock = seconds - poll_interval
        while (clock >= 0 and not self.completed):
            time.sleep(poll_interval)

            poll_results = self.poll()

            for (host, res) in poll_results['polled'].iteritems():
                if res.get('started'):
                    self.runner.callbacks.on_async_poll(host, res, self.jid, clock)

            clock = clock - poll_interval

        return self.results
