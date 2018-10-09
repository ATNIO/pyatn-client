# pyatn-client

**pyatn-client is Python ATN client, used to call DBot's API easily through payment channel**


## Install

To install Python ATN client, simply use pip:

```bash
pip install pyatn-client
```

## Usage

An example could look like this. So simpl:

```python
from pyatn_client import Atn

atn = Atn(
    http_provider='<Web3 Provider>',   # or use offical default one: https://rpc-test.atnio.net
    pk_file='<path to keystore file>',
    pw_file='<path to password file>'
)

DBOTADDRESS = '0xfd4F504F373f0af5Ff36D9fbe1050E6300699230' # address of the DBot you want to test
URI = '/reg'        # uri of the DBot's API endpoint which you want to call
METHOD = 'POST'     # method of the DBot's API endpoint which you want to call
requests_kwargs = {
    "data": {
        "theme": "中秋月更圆"
    }
}

call_count = 1
while call_count <= 12:
    print('Call {}:'.format(call_count))
    response = atn.call_dbot_api(dbot_address=DBOTADDRESS,
                                uri=URI,
                                method=METHOD,
                                **requests_kwargs)
    call_count += 1
    print(response.text)

# close the channel only when you do not need it any more,
# the remain balance in the channel will be returned to your account
atn.close_channel(DBOTADDRESS)

```


In the example, channel will be auto created if no one between your account and the DBot, and channel will be topuped if the remain balance in the channel is not enough. The default deposit value is 10 times the price of endpoint.
This behavior can be changed, the deposit value is determined by `deposit_strategy`, which is a callable function which input parameter is the price of endpoint. You can pass in `deposit_strategy` when init `Atn` or use `set_deposit_strategy` method to change it. It can be set with `None` to disable auto create or topup the channel, then you should create or topup channel by yourself before call the `call_dbot_api` method. Here is an example.


```python
from pyatn_client import Atn

atn = Atn(
    http_provider='<Web3 Provider>',    # or use offical default one: https://rpc-test.atnio.net
    pk_file='<path to keystore file>',
    pw_file='<path to password file>',
    deposit_strategy=None,              # disable auto create or topup channel
)

DBOTADDRESS = '0xfd4F504F373f0af5Ff36D9fbe1050E6300699230' # address of the DBot you want to test
URI = '/reg'        # uri of the DBot's API endpoint which you want to call
METHOD = 'POST'     # method of the DBot's API endpoint which you want to call
requests_kwargs = {
    "data": {
        "theme": "中秋月更圆"
    }
}

# get price of the endpoint to be called
price = atn.get_price(DBOTADDRESS, URI, METHOD)
# open channel with the DBot, only one opened channel is allowed between two address
# it will return the channel if one existed.
channel = atn.open_channel(DBOTADDRESS, 10 * price)
# wait DBot server sync channel info with the blockchain
atn.wait_dbot_sync(DBOTADDRESS)
if channel.deposit - channel.balance < price:
    atn.topup_channel(DBOTADDRESS, 10 * price)
    # wait DBot server sync channel info with the blockchain
    atn.wait_dbot_sync(DBOTADDRESS)

call_count = 1
while call_count <= 12:
    print('Call {}:'.format(call_count))
    # AtnException will raise when eleventh call for insufficient balance, you need catch it
    response = atn.call_dbot_api(dbot_address=DBOTADDRESS,
                                uri=URI,
                                method=METHOD,
                                **requests_kwargs)
    call_count += 1
    print(response.text)

```


## Reference

comming ...
