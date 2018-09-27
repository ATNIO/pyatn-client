# pyatn-client

Python ATN client


## Usage

The python ATN client can be used as a standalone library, to call api easily through payment channel.

An example could look like this:

```python
from pyatn_Client import Atn

PK_FILE = '<path to keystore file>'
PW_FILE = '<path to password file>'
HTTP_PROVIDER = '<Web3 Provider>'  # or use offical default one: https://rpc-test.atnio.net

atn = Atn(
    http_provider=HTTP_PROVIDER,
    pk_file=PK_FILE,
    pw_file=PW_FILE
)

response = atn.call_dbot_api(address=<Address of DBot>,
                             uri=<URI of DBot endpoint>,
                             method=<METHOD of DBot endpoint>,
                             **requests_data)
```
