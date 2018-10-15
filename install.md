# Install pyatn-client

Python ATN client depends on python3.6+, can be installed just by `pip`. And the installation need C compiler.


### Linux

* Ubuntu
```bash
sudo apt-get install build-essential
sudo apt-get install python3
pip3 install pyatn-client
```

* Redhat or CentOS
```bash
yum install gcc
yum install python36 python36-devel
pip3 install pyatn-client
```

### Mac

```bash
xcode-select --install
brew install python3
pip3 install pyatn-client
```

### Windows

Download and install the [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/).

It's cumbersome and takes up more disks to install Visual Studio Build Tools. We have build offline wheel package for the one which need C compiler, you can download and install them first.

**win32**

Download links:
* [cytoolz-0.9.0.1-cp37-cp37m-win32.whl](http://python-wheels.oss-cn-hangzhou.aliyuncs.com/cytoolz-0.9.0.1-cp37-cp37m-win32.whl)
* [lru_dict-1.1.6-cp37-cp37m-win32.whl](https://python-wheels.oss-cn-hangzhou.aliyuncs.com/lru_dict-1.1.6-cp37-cp37m-win32.whl)
```bash
pip install cytoolz-0.9.0.1-cp37-cp37m-win32.whl
pip install lru_dict-1.1.6-cp37-cp37m-win32.whl
```

**win_amd64**

Download links:
* [cytoolz-0.9.0.1-cp37-cp37m-win_amd64.whl](https://python-wheels.oss-cn-hangzhou.aliyuncs.com/cytoolz-0.9.0.1-cp37-cp37m-win_amd64.whl)
* [lru_dict-1.1.6-cp37-cp37m-win_amd64.whl](https://python-wheels.oss-cn-hangzhou.aliyuncs.com/lru_dict-1.1.6-cp37-cp37m-win_amd64.whl)
```bash
pip install cytoolz-0.9.0.1-cp37-cp37m-win_amd64.whl
pip install lru_dict-1.1.6-cp37-cp37m-win_amd64.whl
```

Final install pyatn-client
```bash
pip install pyatn-client
```
