# Copyright 2014-2017 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
#
"""
All required to provide details of build environment 
and allow for reproducable builds

:author: Shahzeb Siddiqui (Pfizer)
"""
import subprocess
import os
import sys
import easybuild.tools.options as eboptions

from vsc.utils import fancylogger
from easybuild.tools.config import build_option, get_module_naming_scheme, package_path
from easybuild.tools.filetools import change_dir, which, write_file
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.testing import  session_state
_log = fancylogger.getLogger('tools.package')  # pylint: disable=C0103

def architecture_query(model_num):
	model_mapping = {
		'4F': 'Broadwell',
		'57': 'KnightsLanding',
		'3F': 'Haswell',
		'46': 'Haswell',
		'3A': 'IvyBridge',
		'3E': 'IvyBridge',
		'2A': 'SandyBridge',
		'2D': 'SandyBridge',
		'25': 'Westmere',
		'2C': 'Westmere',
		'2F': 'Westmere',
		'1E': 'Nehalem',
		'1A': 'Nehalem',
		'2E': 'Nehalem',
		'17': 'Penryn',
		'1D': 'Penryn',
		'0F': 'Merom'
		}
	if model_num in model_mapping.keys():
		return model_mapping[model_num]
	else:
		print "Model Number: ", model_num, " not found in dictionary, please consider adding the model number and Architecture name"
		return None


def generate_singularity_recipe(ordered_ecs,bootstrap_opts):

    container_size = build_option('imagesize')
    container_path = build_option('imagepath')
    image_name = build_option('imagename')
    image_format = build_option('imageformat')
    build_image = build_option('buildimage')

    print "build_image:", build_image
     
    #print ordered_ecs
    bootstrap_list = bootstrap_opts.split(":")
    # checking format of --singularity-bootstrap
    if len(bootstrap_list) > 3 or len(bootstrap_list) <= 1:
    	print """ Invalid Format for --singularity-bootstrap 
		  
		  Must be one of the following

		  --singularity-bootstrap localimage:/path/to/image
		  --singularity-bootstrap shub:<image>:<tag>
		  --singularity-bootstrap docker:<image>:<tag>
		  """
	sys.exit(1)
    # first argument to --singularity-bootstrap is the bootstrap agent (localimage, shub, docker)
    bootstrap_type = bootstrap_list[0]

    # check bootstrap type value and ensure it is localimage, shub, docker
    if bootstrap_type != "localimage" and bootstrap_type != "shub" and bootstrap_type != "docker":
    	print " bootstrap type must be localimage, shub, or docker "
	sys.exit(1)

    # extracting application name,version, version suffix, toolchain name, toolchain version from
    # easyconfig class
    appname = ordered_ecs[0]['ec']['name']
    appver = ordered_ecs[0]['ec']['version']
    appversuffix = ordered_ecs[0]['ec']['versionsuffix']

    tcname = ordered_ecs[0]['ec']['toolchain']['name']
    tcver = ordered_ecs[0]['ec']['toolchain']['version']

    # calculate path where to write container, defaults to $EASYBUILD_PACKAGEPATH
    # if --imagepath is not specified
    if container_path:
    	if os.path.exists(container_path):
	    	container_writepath = container_path
	else:
		msg = "Invalid path: " +  container_path +  " please specify a valid directory path"
		print msg
		EasyBuildError(msg)
		sys.exit(1)

    else:
	container_writepath = package_path()

    modulepath = ""


    # with localimage it only takes 2 arguments. --singularity-bootstrap localimage:/path/to/image
    # checking if path to image is valid and verify image extension is".img or .simg"
    if bootstrap_type == "localimage":
    	bootstrap_imagepath = bootstrap_list[1]
	if os.path.exists(bootstrap_imagepath):
		# get the extension of container image
		image_ext = os.path.splitext(bootstrap_imagepath)[1]
		if image_ext == ".img" or image_ext == ".simg":
    			_log.debug("Image Extension is OK")
		else:
			print "Invalid image extension %s, must be .img or .simg", image_ext
			EasyBuildError("Invalid image extension %s must be .img or .simg", image_ext)
			sys.exit(1)
	else:
		
		print "Can't find image path ", bootstrap_imagepath
		EasyBuildError("Can't find image path %s", bootstrap_imagepath)
		sys.exit(1)

    # if option is shub or docker		
    else:
	bootstrap_image = bootstrap_list[1]
        image_tag = "NONE"
    	# format --singularity-bootstrap shub:<image>:<tag>
        if len(bootstrap_list) == 3:
		image_tag = bootstrap_list[2]

    module_scheme = get_module_naming_scheme()
    
    # bootstrap from local image
    if bootstrap_type == "localimage":
	bootstrap_content = "Bootstrap: " + bootstrap_type + " \n"
	bootstrap_content += "From: " + bootstrap_imagepath + "\n" 
    # default bootstrap is shub or docker
    else:
	    bootstrap_content = "BootStrap: " + bootstrap_type + "\n" 

	    if image_tag == "NONE":
		    bootstrap_content += "From: " + bootstrap_image  + "\n"
	    else:
		    bootstrap_content += "From: " + bootstrap_image + ":" + image_tag  + "\n"
    
    if module_scheme == "HierarchicalMNS":
	    modulepath = "/app/modules/all/Core"
    else:
	    modulepath = "/app/modules/all/"

    post_content = """
%post
su - easybuild
"""
    environment_content = """
%environment
source /etc/profile
"""


    # check if toolchain is specified, that affects how to invoke eb and module load is affected based on module naming scheme
    if tcname != "dummy":

        def_file  = appname + "-" + appver + "-" + tcname + "-" + tcver +  appversuffix + ".def"
	ebfile = os.path.splitext(def_file)[0] + ".eb"
        post_content += "eb " + ebfile  + " --robot --installpath=/app/ --prefix=/scratch --tmpdir=/scratch/tmp  --module-naming-scheme=" + module_scheme + "\n"

	# This would be an example like running eb R-3.3.1-intel2017a.eb --module-naming-scheme=HierarchicalMNS. In HMNS you need to load intel/2017a first then R/3.3.1
        if module_scheme == "HierarchicalMNS":
                environment_content += "module use " + modulepath + "\n" 
        	environment_content +=  "module load " + os.path.join(tcname,tcver) + "\n"
        	environment_content +=  "module load " + os.path.join(appname,appver+appversuffix) + "\n"
	# This would be an example of running eb R-3.3.1-intel2017a.eb with default naming scheme, that will result in only one module load and moduletree will be different	
        else:

                environment_content += "module use " +  modulepath + "\n" 
                environment_content += "module load " + os.path.join(appname,appver+"-"+tcname+"-"+tcver+appversuffix) + "\n"
    # for dummy toolchain module load will be same for EasybuildMNS and HierarchicalMNS but moduletree will not		
    else:
	# this would be an example like eb bzip2-1.0.6.eb. Also works with version suffix easyconfigs
        def_file  = appname + "-" + appver + appversuffix + ".def"
	ebfile = os.path.splitext(def_file)[0] + ".eb"
        post_content += "eb " + ebfile + " --robot --installpath=/app/ --prefix=/scratch --tmpdir=/scratch/tmp  --module-naming-scheme=" + module_scheme + "\n"
	
        environment_content += "module use " +  modulepath + "\n"
        environment_content +=  "module load " + os.path.join(appname,appver+appversuffix) + "\n"

	
    # cleaning up directories in container after build	
    post_content += """exit
rm -rf /scratch/tmp/*
rm -rf /scratch/build
rm -rf /scratch/sources
rm -rf /scratch/ebfiles_repo
"""


    runscript_content = """
%runscript
eval "$@"
"""

    label_content = "\n%labels \n"

# uncomment section below to add architecture details in %labels 
#    label_content += "Architecture " + arch_name + "\n"
#    label_content += "Host " + system_info['hostname'] + "\n"
#    label_content += "CPU  " + system_info['cpu_model'] + "\n"

    # adding all the regions for writing the  Singularity definition file
    content = bootstrap_content + post_content + runscript_content + environment_content + label_content
    change_dir(container_writepath)
    write_file(def_file,content)

    print "Writing Singularity Definition File: %s" % os.path.join(container_writepath,def_file)

    # if easybuild will create and build container
    print "name=",image_name
    if build_image:
    	container_name = ""

	if image_name != None:
		ext =  os.path.splitext(image_name)[1] 
		if ext == ".img" or ext == ".simg":
			_log.debug("Extension for image is okay from --image-name")
		else:
			print "Invalid Extension for --imagename ", ext
			EasyBuildError("Invalid Extension for --imagename %s", ext)
			sys.exit(1)

		container_name = image_name
	else:
		container_name = os.path.splitext(def_file)[0]
	    
	#squash image format
	if image_format == "squashfs":
		container_name += ".simg"
		os.system("sudo singularity image.create -s " + str(container_size) + " " + container_name)
		os.system("sudo singularity build " + container_name + " " + def_file)

	# ext3 image format, creating as writable container 
	elif image_format == "ext3":
	    	container_name += ".img"
		os.system("sudo singularity image.create -s " + str(container_size) + " " + container_name)
		os.system("sudo singularity build --writable " + container_name + " " + def_file)

	# sandbox image format, creates as a directory but acts like a container
	elif image_format == "sandbox":
	     	os.system("sudo singularity build --sandbox " + container_name + " " + def_file)


    return 




def check_singularity(ordered_ecs,bootstrap_opts):
    """
    Return build statistics for this build
    """

    singularity_path = which("singularity")
    singularity_version = 0
    if singularity_path:
	print "Singularity tool found at %s" % singularity_path
	ret = subprocess.Popen("singularity --version", shell=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	# singularity version format for 2.3.1 and higher is x.y-dist
	singularity_version = ret.communicate()[0].split("-")[0]
    else:
	print "Singularity not found in your system."
 	EasyBuildError("Singularity not found in your system")


    if float(singularity_version) < 2.4:
    	EasyBuildError("Please upgrade singularity instance to version 2.4.1 or higher")
    else:
	print "Singularity version is 2.4 or higher ... OK"
	print "Singularity Version is " + singularity_version

# ---------- uncomment section below when enabling architecture detection and labels in singularity

    #buildsystem_session = session_state()
    #system_info = buildsystem_session['system_info']

    #ret = subprocess.Popen("""lscpu | grep Model: | cut -f2 -d ":" """,shell=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    #model_num = int(ret.communicate()[0])

    # convert decimal to hex. Output like  0x3e. Take everything after x and convert to uppercase
    #model_num = hex(model_num).split('x')[-1].upper()
    #arch_name = architecture_query(model_num)

    generate_singularity_recipe(ordered_ecs, bootstrap_opts)

    return 
