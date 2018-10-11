import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pyatn-client",
    version="0.0.6",
    author="ovsoil",
    author_email="huaxin.yu@atmatrix.org",
    description="Python ATN Client",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ATNIO/pyatn-client",
    packages=setuptools.find_packages(),
    install_requires=[
        'click==6.7',
        'requests==2.19.1',
        'coincurve==9.0.0',
        'eth_account==0.3.0',
        'eth_keyfile==0.5.1',
        'eth_utils==1.2.2',
        'ethereum==2.3.2',
        'gevent==1.3.6',
        'munch==2.3.2',
        'rlp==1.0.2',
        'typing==3.6.6',
        'web3==4.7.2'
    ],
    package_data={
        '': ['contracts.json', 'microraiden/contracts.json']
    },
    scripts=[
        'pyatn'
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
