#!/usr/bin/env python

# Copyright (c) 2013, Carnegie Mellon University
# All rights reserved.
# Authors: Michael Koval <mkoval@cs.cmu.edu>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 
# - Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# - Neither the name of Carnegie Mellon University nor the names of its
#   contributors may be used to endorse or promote products derived from this
#   software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import openravepy, threading

class CloneException(Exception):
    pass

class Clone(object):
    local = threading.local()

    def __init__(self, parent_env, clone_env=None, destroy_on_exit=None,
                 options=openravepy.CloningOptions.Bodies):
        """
        Context manager that clones the parent environment.

        If clone_env is specified, then parent_env will be cloned into
        clone_env. Otherwise, a new environment will be created and cloned from
        parent_env. If clone_env is dynamically created, it will be destroyed
        on exit by default unless the destroy_on_exit argument is false.

        @param parent_env environment to clone
        @param clone_env environment to clone into (optional)
        @param destroy_on_exit whether to destroy the clone on __exit__
        @param options bitmask of CloningOptions
        """

        self.__class__.get_envs().append(clone_env)

        self.clone_parent = parent_env
        self.options = options

        if clone_env is not None:
            self.clone_env = clone_env
        else:
            self.clone_env = openravepy.Environment()

        if destroy_on_exit is not None:
            self.destroy_on_exit = destroy_on_exit
        else:
            # By default, only destroy the environment if we implicitly created
            # it. Otherwise, the user might expect it to still be around.
            self.destroy_on_exit = clone_env is None

        # Actually clone.
        with self.clone_env:
            with self.clone_parent:
                self.clone_env.Clone(self.clone_parent, self.options)

            # Required for InstanceDeduplicator to call CloneBindings for
            # PrPy-annotated classes.
            setattr(self.clone_env, 'clone_parent', self.clone_parent)

    def __enter__(self):
        return self.clone_env

    def __exit__(self, *args):
        if self.destroy_on_exit:
            self.Destroy()
        else:
            self.__class__.get_envs().pop()

    def Destroy(self):
        self.__class__.get_envs().pop()

        # Manually Remove() all objects from the environment. This forces
        # OpenRAVE to call functions registered to RegisterBodyCallback.
        # Otherwise, these functions are only called when the environment is
        # destructed. This is too late for prpy.bind to cleanup circular
        # references.
        # TODO: Make this the default behavior in OpenRAVE.
        for body in self.clone_env.GetBodies():
            import prpy.bind
            prpy.bind.InstanceDeduplicator.cleanup_callback(body, flag=0)

        openravepy.Environment.Destroy(self.clone_env)
        self.clone_env.SetUserData(None)

    @classmethod
    def get_env(cls):
        environments = cls.get_envs()
        if not environments:
            raise CloneException(
                'Cloned environments may only be used in a Clone context.'
            )
        return environments[-1]

    @classmethod
    def get_envs(cls):
        if not hasattr(cls.local, 'environments'):
            cls.local.environments = list()
        return cls.local.environments

def Cloned(*instances):
    clone_env = Clone.get_env()
    clone_instances = list()

    for instance in instances:
        if isinstance(instance, openravepy.Robot):
            clone_instance = clone_env.GetRobot(instance.GetName())
        elif isinstance(instance, openravepy.KinBody):
            clone_instance = clone_env.GetKinBody(instance.GetName())
        elif isinstance(instance, openravepy.KinBody.Link):
            clone_instance = Cloned(instance.GetParent()).GetLink(instance.GetName())
        elif isinstance(instance, openravepy.Robot.Manipulator):
            clone_instance = Cloned(instance.GetRobot()).GetManipulator(instance.GetName())
        else:
            raise CloneException('Unable to clone object of type {0:s}.'.format(type(instance)))

        if clone_instance is None:
            raise CloneException('{0:s} is not in the cloned environment.'.format(instance))

        clone_instance.clone_parent = instance
        clone_instances.append(clone_instance)

    if len(instances) == 1:
        return clone_instances[0]
    else:
        return clone_instances
