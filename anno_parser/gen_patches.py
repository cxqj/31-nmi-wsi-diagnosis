# -*- coding: utf-8 -*-

import os, sys
import numpy as np
import argparse
import openslide
import cv2
import uuid, json
from skimage import transform, io
import matplotlib.pyplot as plt
'''
轮廓是许多基于图像的应用中最重要的概念之一，主要用于表示感兴趣区域(ROI)，特别是在医学图像应用中。
OpenCV和shapely都提供了一些轮廓功能。但是，对于开发人员来说，轮廓表示看起来很模糊和奇怪。
这个包试图对python中的轮廓表示进行标准化。与OpenCV不同的是，这里的轮廓是一个形状为2*N (0-h 1-w)的numpy二维数组，
其中高度总是第一位的，如图所示。我们相信这种表现形式是开发人员理解和使用的最直观的方式。此外，还支持使用OpenCV或shapely
在此表示之间来回转换，使开发人员能够利用OpenCV和shapely的功能。
'''
from pycontour import poly_transform
from shapely.geometry import Point   # 这个 Point 构造函数接受位置坐标值或点元组参数。
import matplotlib.pyplot as plt
from load_anno import load_annotation


def get_save_dirs(args):
    patch_label = None

    if args.anno_type == "Neg":
        patch_label = "3"
    elif args.anno_type == "Pos":
        diagnosis_dict = {}
        if args.dset == "train":
            diagnosis_dict = json.load(open(os.path.join(args.bladder_dir, "Slide", "train_diagnosis_partial.json")))
        elif args.dset == "test":
            diagnosis_dict = json.load(open(os.path.join(args.bladder_dir, "Slide", "val_test_diagnosis_partial.json")))
        else:
            print("Unkonwn dataset {}".format(args.dset))
            sys.exit()
        if args.slide_id not in diagnosis_dict:
            print("The diagnosis of {} is unknown".format(args.slide_id))
            sys.exit()
        else:
            patch_label = str(diagnosis_dict[args.slide_id])   # 诊断的患病级别
    else:
        print("Unknonw annotation type {}".format(args.anno_type))
        sys.exit()

    img_save_dir = os.path.join(args.bladder_dir, "segmentation", args.dset, "img", patch_label)
    if not os.path.exists(img_save_dir):
        os.makedirs(img_save_dir)
    mask_save_dir = os.path.join(args.bladder_dir, "segmentation", args.dset, "groundTruth", patch_label)
    if not os.path.exists(mask_save_dir):
        os.makedirs(mask_save_dir)

    return img_save_dir, mask_save_dir



def gen_patch_mask(args):
    patch_mask = None
    if args.anno_type == "Neg":
        patch_mask = np.ones((args.crop_size, args.crop_size), dtype=np.uint8) * 155
    elif args.anno_type == "Pos":
        patch_mask = np.ones((args.crop_size, args.crop_size), dtype=np.uint8) * 255
    else:
        print("Unknonw annotation type {}".format(args.anno_type))
        sys.exit()

    return patch_mask  # (1024,1024)


# annotation_dict : 坐标字典
def gen_patches(slide_path, annotation_dict, args):
    """ Generate patch images and masks based on annotations as well as slide information.

    """

    # load slide header information
    slide_head = openslide.OpenSlide(slide_path)  # 读取图像
    slide_name = os.path.basename(slide_path)  # slide id 
    # level_count——幻灯片中的级别数。级别从0（最高分辨率）到level_count - 1（最低分辨率）编号。
    if args.slide_level < 0 or args.slide_level >= slide_head.level_count:    # slide_head.level_count  = 4 
        print("level {} not availabel in {}".format(args.slide_level, slide_name))
        sys.exit()

    img_save_dir, mask_save_dir = get_save_dirs(args)
    
    for cur_reg in annotation_dict:
        # slide_head.level_downsamples[args.slide_level = 1.0
        # 原始坐标是(w,h)
        
        coords = (annotation_dict[cur_reg] / slide_head.level_downsamples[args.slide_level]).astype(np.int32)
        coords = np.transpose(np.array(coords))  # (2,428)
        coords[[0, 1]] = coords[[1, 0]] # swap width and height
        min_h, max_h = np.min(coords[0, :]), np.max(coords[0, :])   # 0 is height   (22,20464)
        min_w, max_w = np.min(coords[1, :]), np.max(coords[1, :])   # 1 is width    (6119,33036)

        num = 0
        
        # 使用numpy二维数组([0]-h， [1]-w)构造多边形, 需要注意的是，高度是第一维，宽度是第二维
        cur_poly = poly_transform.np_arr_to_poly(np.asarray(coords))  # 生成多边形
        
        # 一个图片滑动10次
        while num < 10:
            rand_h = np.random.randint(min_h, max_h)
            rand_w = np.random.randint(min_w, max_w)
            
             # 原始坐标是(w,h)
            h_over_flag = rand_h + args.crop_size >= slide_head.level_dimensions[args.slide_level][1]
            w_over_flag = rand_w + args.crop_size >= slide_head.level_dimensions[args.slide_level][0]
            if h_over_flag or w_over_flag:
                continue

            cen_h = int(rand_h + args.crop_size / 2)  # (5385)
            cen_w = int(rand_w + args.crop_size / 2)  # (14173)
            cen_point = Point(cen_w, cen_h)   # 构造几何图形中心点  (14173,5385)
            
            
            patch_in_flag = cen_point.within(cur_poly)  # 判断中心点是否在多边形之中
            
            if not patch_in_flag:
                num += 1
                continue

            # 将(1024,1024)的区域按随机生成的(rand_h,rand_w)裁剪出来
            cur_patch = slide_head.read_region((rand_w, rand_h), args.slide_level, (args.crop_size, args.crop_size))  # shape : (1024,1024)
            cur_patch = np.asarray(cur_patch)[:,:,:3]  # (1024,1024)-->(1024,1024,3)

            # correct patch mask on ignore pixels
            ## very slow, need to speed this ignore part   1024x1024次迭代
            patch_mask = gen_patch_mask(args)
            
            for pw in range(rand_w, rand_w+args.crop_size):
                for ph in range(rand_h, rand_h+args.crop_size):
                    cur_p = Point(pw, ph)   # 当前坐标点
                    # 如果坐标点不在多边形曲线内，则mask置为0
                    if not cur_p.within(cur_poly):
                        patch_mask[ph-rand_h, pw-rand_w] = 0

                
            save_img = transform.resize(cur_patch, (args.save_size, args.save_size))  # (256,256,3)
            # 经过resize后变为了0或1的矩阵  (256,256)
            save_mask = transform.resize(patch_mask, (args.save_size, args.save_size), order=0) # order=0: Nearest-neighbor interpolation
            
            save_mask = (save_mask * 255).astype(np.uint8)

            img_fullname = str(uuid.uuid4())[:8]+".png"   # 随机生成8位唯一的id
            save_img_path = os.path.join(img_save_dir, img_fullname)
            save_mask_path = os.path.join(mask_save_dir, img_fullname)
            io.imsave(save_img_path, save_img)
            io.imsave(save_mask_path, save_mask)
            num = num + 1


def set_args():
    parser = argparse.ArgumentParser(description='Bladder slide annotation loading and visulization')
    parser.add_argument('--bladder_dir', type=str, default="../data",
                        help="folder that contains bladder data") # change based on your bladder data location
    parser.add_argument('--anno_type',   type=str, default="Pos", choices=["Pos", "Neg"])
    parser.add_argument('--dset',        type=str, default="train", choices=["train", "test"])
    parser.add_argument('--slide_id',    type=str, default="1_00061_sub0")
    parser.add_argument('--crop_size',   type=int, default=1024)
    parser.add_argument('--save_size',   type=int, default=256)
    parser.add_argument('--slide_level', type=int, default=0)  # 最高分辨率

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = set_args()

    # locate annotation path
    anno_path = os.path.join(args.bladder_dir, "Slide", "RegionAnnotation",
                             args.anno_type, args.slide_id, "annotations.json")
    if not os.path.exists(anno_path):
        print("No {} annotation for slide {}".format(args.anno_type, args.slide_id))
        sys.exit()
    # load annotation
    annotation_dict = load_annotation(anno_path)  # {'region_name' : coords}

    # find slide path (slide filename extension can be .svs or .tiff)
    slide_dir = os.path.join(args.bladder_dir, "Slide", "Img")
    if os.path.exists(os.path.join(slide_dir, args.slide_id+".svs")):
        slide_path = os.path.join(slide_dir, args.slide_id+".svs")
    elif os.path.exists(os.path.join(slide_dir, args.slide_id+".tiff")):
        slide_path = os.path.join(slide_dir, args.slide_id+".tiff")
    else:
        print("Slide {} not exist".format(args.slide_id))
        sys.exit()

    # overlay the annotation on the slide and display
    gen_patches(slide_path, annotation_dict, args)
    
    
