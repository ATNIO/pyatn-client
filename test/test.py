#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pyatn_client import Atn

# API info
DBOTADDRESS = '0xfd4F504F373f0af5Ff36D9fbe1050E6300699230' # address of the DBot you want to test, use 'AI poetry' as example
URI = '/reg'        # uri of the DBot's API endpoint which you want to call
METHOD = 'POST'     # method of the DBot's API endpoint which you want to call
requests_kwargs = {
    "data": {
        "theme": "中秋月更圆"
    }
}

# Init Atn
atn = Atn(
    pk_file='./dbot-examples/accounts/signer02/keystore/UTC--2018-06-19T08-46-10.312652809Z--0cc1f6e1a55b163301434a47b1cb68cbd7e27cad',
    pw_file='./dbot-examples/accounts/signer02/password/passwd'
)

# Call a DBot API 12 times
for i in range(12):
    response = atn.call_dbot_api(dbot_address=DBOTADDRESS,
                                uri=URI,
                                method=METHOD,
                                **requests_kwargs)
    print('Call {}:\n{}'.format(i + 1, response.text))

# close the channel only when you do not need it any more,
# the remain balance in the channel will be returned to your account
atn.close_channel(DBOTADDRESS)
