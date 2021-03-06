import os, sys, pdb
import glob, random
import numpy as np
import itertools
from collections import Counter
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

from data_generator.image import ImageDataGenerator

def preprocess(img, mean, std, label, normalize_label=False):
    out_img = img / img.max() # scale to [0,1]
    out_img = (out_img - np.array(mean).reshape(1,1,3)) / np.array(std).reshape(1,1,3)

    if normalize_label:
        if np.unique(label).size > 2:
            print ('WRANING: the label has more than 2 classes. Set normalize_label to False')
        label = label / label.max() # if the loaded label is binary has only [0,255], then we normalize it
    return out_img, label.astype(np.int32)

def deprocess(img, mean, std, label):
    out_img = img / img.max() # scale to [0,1]
    out_img = (out_img * np.array(std).reshape(1,1,3)) + np.array(std).reshape(1,1,3)
    out_img = out_img * 255.0

    return out_img.astype(np.uint8), label.astype(np.uint8)

"""
data_weigthed_loader consider the label for specific treatmentss
"""

def data_loader(path, batch_size, imSize,
                        mean=[0.5,0.5,0.5], std=[0.5,0.5,0.5],
                        ignore_val=44, pos_val=255, neg_val=155, pos_class=[0,1], neg_class=[2]):
    # pos_class and neg_class in the folder name for keras ImageDataGenerator input
    # 0,1,2 are low, high, normal

    def imerge(img_gen, mask_gen):
        # imgs : (2,256,256,3)  img_labels : [0,0]   
        # mask : (2,256,256,1)  mask_labels : [0,0]
        # itertools.zip_longest： 使用最长的迭代器来作为返回值的长度，并且可以使用fillvalue来制定那些缺失值的默。
        for (imgs, img_labels), (mask, mask_labels) in itertools.zip_longest(img_gen, mask_gen):
            # compute weight to ignore particular pixels
            # mask = np.expand_dims(mask[:,:,:,0], axis=3)
            mask = mask[:,:,:,0]  # (2,256,256)
            weight = np.ones(mask.shape, np.float32) # (2,256,256)
            weight[mask==ignore_val] = 0.5 # this is set by experience

            # In mask, ignored pixel has value ignore_val.
            # The weight of these pixel is set to zero, so they do not contribute to loss
            # The returned mask is still binary.
            # compute per sample
            
            
            # pos_val : 255
            # neg_val : 155
            # ignore_val : 44
            for c, mask_label in enumerate(mask_labels):
                assert(mask_labels[c] == img_labels[c])
                mask_pointer = mask[c]   # mask像素点
                if mask_label in pos_class:
                    assert(np.where(mask_pointer == neg_val)[0].size == 0)
                    mask_pointer[mask_pointer==pos_val] = 1
                elif mask_label in neg_class:
                    assert(np.where(mask_pointer == pos_val)[0].size == 0)
                    mask_pointer[mask_pointer==neg_val] = 0
                else:
                    print ('WARNING: mask beyond the expected class range')
                    mask_pointer /= 255.0

                mask_pointer[mask_pointer==ignore_val] = 0

            # issubset() 方法用于判断集合的所有元素是否都包含在指定集合中，如果是则返回 True，否则返回 False。
            # 对于一维数组或者列表，unique函数去除其中重复的元素，并按元素由大到小返回一个新的无元素重复的元组或者列表
            assert set(np.unique(mask)).issubset([0, 1])
            # assert set(np.unique(weight)).issubset([0, 1])

            # img, mask = preprocess(imgs, mean, std, mask)

            yield imgs, mask, weight, img_labels
    # 训练数据配置参数
    train_data_gen_args = dict(
                    horizontal_flip=True,
                    zoom_range=0.2,
                    fill_mode='reflect')

    seed = 1234
    # 1.初始化 ImageDataGenerator
    # 2.调用flow_from_directory,返回Directory()对象
    # 3.在调用next()函数时才进入Directory类中进行迭代
    train_image_datagen = ImageDataGenerator(**train_data_gen_args).flow_from_directory(
                                path+'train/img',
                                class_mode="sparse",   # sparse : 稀疏
                                target_size=(imSize, imSize),
                                batch_size=batch_size,
                                seed=seed)
    train_mask_datagen = ImageDataGenerator(**train_data_gen_args).flow_from_directory(
                                path+'train/groundTruth',
                                class_mode="sparse",
                                target_size=(imSize, imSize),
                                batch_size=batch_size,
                                color_mode='grayscale',
                                seed=seed)

    test_image_datagen = ImageDataGenerator().flow_from_directory(
                                path+'test/img',
                                class_mode="sparse",
                                target_size=(imSize, imSize),
                                batch_size=batch_size,
                                seed=seed)
    test_mask_datagen = ImageDataGenerator().flow_from_directory(
                                path+'test/groundTruth',
                                class_mode="sparse",
                                target_size=(imSize, imSize),
                                batch_size=batch_size,
                                color_mode='grayscale',
                                seed=seed)

    train_generator = imerge(train_image_datagen, train_mask_datagen)
    test_generator = imerge(test_image_datagen, test_mask_datagen)
    sys.stdout.flush()  # 在Linux系统下，必须加入sys.stdout.flush()才能一秒输一个数字
    return train_generator,  test_generator, train_image_datagen.samples, test_image_datagen.samples
