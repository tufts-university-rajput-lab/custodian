import os
import shutil
from glob import glob

from custodian.nwchem.handlers import NwchemErrorHandler
from tests.conftest import TEST_FILES

__author__ = "shyuepingong"
__version__ = "0.1"
__maintainer__ = "Shyue Ping Ong"
__email__ = "shyuep@gmail.com"
__status__ = "Beta"
__date__ = "6/18/13"


def test_check_correct():
    os.chdir(f"{TEST_FILES}/nwchem")
    shutil.copy("C1N1Cl1_1.nw", "C1N1Cl1_1.nw.orig")
    handler = NwchemErrorHandler(output_filename="C1N1Cl1_1.nwout")
    handler.check()
    handler.correct()
    shutil.move("C1N1Cl1_1.nw.orig", "C1N1Cl1_1.nw")
    shutil.copy("Li1_1.nw", "Li1_1.nw.orig")
    handler = NwchemErrorHandler(output_filename="Li1_1.nwout")
    handler.check()
    handler.correct()
    shutil.move("Li1_1.nw.orig", "Li1_1.nw")
    for file in glob("error.*.tar.gz"):
        os.remove(file)
