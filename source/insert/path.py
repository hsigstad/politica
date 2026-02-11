import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.append("{}/source/clean".format(os.environ["BASE_DIR"]))
sys.path.append("{}/source/insert".format(os.environ["BASE_DIR"]))

data_dir = os.environ["DATA_DIR"]
