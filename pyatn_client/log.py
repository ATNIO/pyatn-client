#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import logging
from logging.handlers import RotatingFileHandler

LOGPATH = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOGPATH, exist_ok=True)

class AtnLogger():
    def __init__(self, name: str):
        self._name = name

    def config(self):
        return {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {
                'verbose': {
                    'format': '%(asctime)s %(name)s(%(levelname)s) %(message)s (%(filename)s[%(lineno)d])'
                },
                'normal': {
                    'format': '%(asctime)s %(levelname)-8s %(message)s'
                },
                'simple': {
                    'format': '%(levelname)s %(message)s'
                },
            },
            'handlers': {
                'console':{
                    'level': 'INFO',
                    'class':'logging.StreamHandler',
                    'formatter': 'simple'
                },
                'info_file': {
                    'level': 'INFO',
                    'class': 'logging.handlers.RotatingFileHandler',
                    'formatter': 'normal',
                    'filename': os.path.join(LOGPATH, '{}.log'.format(self._name)),
                    'encoding': 'utf8',
                    'mode': 'a',
                    'maxBytes': 10485760,
                    'backupCount': 5
                },
                'debug_file': {
                    'level': 'DEBUG',
                    'class': 'logging.handlers.RotatingFileHandler',
                    'formatter': 'verbose',
                    'filename': os.path.join(LOGPATH, '{}_debug.log'.format(self._name)),
                    'encoding': 'utf8',
                    'mode': 'a',
                    'maxBytes': 10485760,
                    'backupCount': 20
                },
            },
            'loggers': {
                'atn': {
                    'handlers': ['console', 'info_file', 'debug_file'],
                    'level': 'DEBUG',
                    'propagate': False
                }
            },
            'root': {
                'handlers': ['console', 'info_file', 'debug_file'],
                'level': 'DEBUG',
            }
        }
