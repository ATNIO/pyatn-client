#!/usr/bin/env python
# -*- coding: utf-8 -*-

def remove_slash_prefix(uri):
    if uri.startswith('/'):
        return uri[1:]
    else:
        return uri

def tobytes32(s):
    length = len(s.encode('utf-8'))
    assert(length <= 256)
    return  s.encode('utf-8') + b'\0' * (32 - length)
