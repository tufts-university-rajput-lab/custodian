# coding: utf-8

"""
This module implements error handlers for Gaussian runs.
"""

import os
import re
import glob
import logging

import numpy as np
import matplotlib.pyplot as plt

from monty.io import zopen

from pymatgen.io.gaussian import GaussianInput, GaussianOutput

from custodian.utils import backup
from custodian.custodian import ErrorHandler

__author__ = 'Rasha Atwi'
__version__ = '0.0'
__maintainer__ = 'Rasha Atwi'
__email__ = 'rasha.atwi@stonybrook.edu'
__status__ = 'Alpha'
__date__ = '5/13/21'


# logger = logging.getLogger(__name__)


class GaussianErrorHandler(ErrorHandler):
    error_defs = {'Optimization stopped': 'opt_steps',
                  'Convergence failure': 'scf_convergence',
                  'FormBX had a problem': 'linear_bend',
                  'Inv3 failed in PCMMkU': 'solute_solvent_surface'}
    error_patt = re.compile('|'.join(list(error_defs)))
    conv_critera = {
        'max_force': re.compile(
            r'\s+(Maximum Force)\s+(-?\d+.?\d*|.*)\s+(-?\d+.?\d*)'),
        'rms_force': re.compile(
            r'\s+(RMS {5}Force)\s+(-?\d+.?\d*|.*)\s+(-?\d+.?\d*)'),
        'max_disp': re.compile(
            r'\s+(Maximum Displacement)\s+(-?\d+.?\d*|.*)\s+(-?\d+.?\d*)'),
        'rms_disp': re.compile(
            r'\s+(RMS {5}Displacement)\s+(-?\d+.?\d*|.*)\s+(-?\d+.?\d*)')}
    activate_better_scf_guess = False

    def __init__(
            self,
            input_file,
            output_file,
            stderr_file='stderr.txt',
            cart_coords=True,
            scf_max_cycles=100,
            opt_max_cycles=100,
            job_type='normal',
            scf_functional=None,
            scf_basis_set=None,
            prefix='error',
            check_convergence=True
    ):
        self.input_file = input_file
        self.output_file = output_file
        self.stderr_file = stderr_file
        self.cart_coords = cart_coords
        self.errors = set()
        self.gout = None
        self.gin = None
        self.scf_max_cycles = scf_max_cycles
        self.opt_max_cycles = opt_max_cycles
        self.job_type = job_type
        self.scf_functional = scf_functional
        self.scf_basis_set = scf_basis_set
        self.prefix = prefix
        self.check_convergence = check_convergence
        self.conv_data = None
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def _recursive_lowercase(obj):
        if isinstance(obj, dict):
            updated_obj = {}
            for k, v in obj.items():
                updated_obj[k.lower()] = \
                    GaussianErrorHandler._recursive_lowercase(v)
            return updated_obj
        elif isinstance(obj, str):
            return obj.lower()
        elif hasattr(obj, '__iter__'):
            updated_obj = []
            for i in obj:
                updated_obj.append(GaussianErrorHandler._recursive_lowercase(i))
            return updated_obj
        else:
            return obj

    @staticmethod
    def _monitor_convergence(data):
        fig, ax = plt.subplots(ncols=2, nrows=2, figsize=(12, 10))
        for i, (k, v) in enumerate(data['values'].items()):
            row = int(np.floor(i / 2))
            col = i % 2
            iters = range(0, len(v))
            ax[row, col].plot(iters, v, color='#cf3759',
                              linewidth=2)
            ax[row, col].axhline(y=data['thresh'][k], linewidth=2,
                                 color='black',
                                 linestyle='--')
            ax[row, col].tick_params(which='major', length=8)
            ax[row, col].tick_params(axis='both', which='both',
                                     direction='in',
                                     labelsize=16)
            ax[row, col].set_xlabel('Iteration', fontsize=16)
            ax[row, col].set_ylabel('{}'.format(k), fontsize=16)
            ax[row, col].set_xticks(iters)
            ax[row, col].grid(ls='--', zorder=1)
        plt.tight_layout()
        plt.savefig('convergence.png')

    def check(self):
        self.gin = GaussianInput.from_file(self.input_file)
        self.gin.route_parameters = \
            GaussianErrorHandler._recursive_lowercase(self.gin.route_parameters)
        self.gout = GaussianOutput(self.output_file)
        self.errors = set()
        error_patts = set()
        # TODO: move this to pymatgen?
        self.conv_data = {'values': {}, 'thresh': {}}
        with zopen(self.output_file) as f:
            for line in f:
                if GaussianErrorHandler.error_patt.search(line):
                    m = GaussianErrorHandler.error_patt.search(line)
                    patt = m.group(0)
                    error_patts.add(patt)
                    self.errors.add(GaussianErrorHandler.error_defs[patt])

                if self.check_convergence and 'opt' in self.gin.route_parameters:
                    for k, v in GaussianErrorHandler.conv_critera.items():
                        if v.search(line):
                            m = v.search(line)
                            if k not in self.conv_data['values']:
                                self.conv_data['values'][k] = [
                                    float(m.group(2))]
                                self.conv_data['thresh'][k] = float(m.group(3))
                            else:
                                self.conv_data['values'][k].append(
                                    float(m.group(2)))
        # TODO: it only plots after the job finishes, modify
        if self.check_convergence and 'opt' in self.gin.route_parameters:
            GaussianErrorHandler._monitor_convergence(self.conv_data)

        for patt in error_patts:
            self.logger.error(patt)
        return len(self.errors) > 0

    def correct(self):
        actions = []
        backup_files = [self.input_file, self.output_file, self.stderr_file]
        try:
            checkpoint = glob.glob('*.chk')[0]
            backup_files.append(checkpoint)
            form_checkpoint = glob.glob('*.fchk')[0]
            backup_files.append(form_checkpoint)
        except Exception:
            pass
        backup(backup_files, self.prefix)
        if 'scf_convergence' in self.errors:
            # if the SCF procedure has failed to converge
            if self.gin.route_parameters.get('scf').get('maxcycle') != \
                    str(self.scf_max_cycles):
                # increase number of cycles if not already set or is different
                # from scf_max_cycles
                self.gin.route_parameters['scf']['maxcycle'] = \
                    self.scf_max_cycles
                actions.append({'scf_max_cycles': self.scf_max_cycles})

            elif not {'xqc', 'yqc', 'qc'}.intersection(
                    self.gin.route_parameters.get('scf')):
                # use an alternate SCF converger
                self.gin.route_parameters['scf']['xqc'] = None
                actions.append({'scf_algorithm': 'xqc'})

            elif self.job_type == 'better_scf_guess' and not \
                    GaussianErrorHandler.activate_better_scf_guess:
                # try to get a better initial guess at a lower level of theory
                self.logger.info('SCF calculation failed. Switching to a lower '
                                 'level of theory to get a better initial '
                                 'guess of molecular orbitals')
                # TODO: what if inputs don't work with scf_lot? e.g. extra_basis
                self.gin.functional = self.scf_functional
                self.gin.basis_set = self.scf_basis_set
                actions.append({'scf_level_of_theory': 'better_scf_guess'})
                GaussianErrorHandler.activate_better_scf_guess = True

            else:
                if self.job_type != 'better_scf_guess':
                    self.logger.info(
                        'Try to switch to better_scf_guess job type to '
                        'generate a different initial guess using a '
                        'lower level of theory')
                else:
                    self.logger.info('SCF calculation failed. Exiting...')
                return {'errors': self.errors, 'actions': None}
        elif 'FormBX had a problem.' in self.errors:
            # if there is some linear bend around an angle in the geometry
            # restart the job at the point it stopped while forcing Gaussian
            # to rebuild the set of redundant internals
            if not self.gin.link0_parameters('%chk'):
                raise KeyError('This remedy reads coords from checkpoint '
                               'file. Consider adding CHK to link0_parameters')
            # TODO: check route_parameters: do I need to keep them?
            # TODO: test
            else:
                self.gin = GaussianInput(
                    mol=None,
                    charge=self.gin.charge,
                    spin_multiplicity=self.gin.spin_multiplicity,
                    title=self.gin.title,
                    functional=self.gin.functional,
                    basis_set=self.gin.basis_set,
                    route_parameters={'geom': '(checkpoint, newdefinition)'},
                    input_parameters=self.gin.input_parameters,
                    link0_parameters=self.gin.link0_parameters,
                    dieze_tag=self.gin.dieze_tag,
                    gen_basis=self.gin.gen_basis)
        os.rename(self.input_file, self.input_file + '.prev')
        self.gin.write_file(self.input_file, self.cart_coords)
        return {'errors': list(self.errors), 'actions': actions}
