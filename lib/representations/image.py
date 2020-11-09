import numpy as np
from scipy.stats import rankdata
import torch

def events_to_image(xs, ys, ps, sensor_size=(180, 240), interpolation=None, padding=False, meanval=False, default=0):
    """
    Place events into an image using numpy
    :param xs: x coords of events
    :param ys: y coords of events
    :param ps: event polarities/weights
    :param sensor_size: the size of the event camera sensor
    :param interpolation: whether to add the events to the pixels by interpolation (values: None, 'bilinear')
    :param padding: If true, pad the output image to include events otherwise warped off sensor
    :param meanval: If true, divide the sum of the values by the number of events at that location
    """
    img_size = sensor_size
    if interpolation == 'bilinear' and xs.dtype is not torch.long and xs.dtype is not torch.long:
        xt, yt, pt = torch.from_numpy(xs), torch.from_numpy(ys), torch.from_numpy(ps)
        xt, yt, pt = xt.float(), yt.float(), pt.float()
        img = events_to_image_torch(xt, yt, pt, clip_out_of_range=True, interpolation='bilinear', padding=padding)
        img[img==0] = default
        img = img.numpy()
        if meanval:
            event_count_image = events_to_image_torch(xt, yt, torch.ones_like(xt), 
                    clip_out_of_range=True, padding=padding)
            event_count_image = event_count_image.numpy()
    else:
        coords = np.stack((ys, xs))
        try:
            abs_coords = np.ravel_multi_index(coords, sensor_size)
        except ValueError:
            print("Issue with input arrays! minx={}, maxx={}, miny={}, maxy={}, coords.shape={}, \
                    sum(coords)={}, sensor_size={}".format(np.min(xs), np.max(xs), np.min(ys), np.max(ys),
                        coords.shape, np.sum(coords), sensor_size))
            raise ValueError
        img = np.bincount(abs_coords, weights=ps, minlength=sensor_size[0]*sensor_size[1])
        img = img.reshape(sensor_size)
        if meanval:
            event_count_image = np.bincount(abs_coords, weights=np.ones_like(xs), minlength=sensor_size[0]*sensor_size[1])
            event_count_image = event_count_image.reshape(sensor_size)
    if meanval:
        img = np.divide(img, event_count_image, out=np.ones_like(img)*default, where=event_count_image!=0)
    return img

def events_to_image_torch(xs, ys, ps,
        device=None, sensor_size=(180, 240), clip_out_of_range=True,
        interpolation=None, padding=True, default=0):
    """
    Method to turn event tensor to image. Allows for bilinear interpolation.
        :param xs: tensor of x coords of events
        :param ys: tensor of y coords of events
        :param ps: tensor of event polarities/weights
        :param device: the device on which the image is. If none, set to events device
        :param sensor_size: the size of the image sensor/output image
        :param clip_out_of_range: if the events go beyond the desired image size,
            clip the events to fit into the image
        :param interpolation: which interpolation to use. Options=None,'bilinear'
        :param padding if bilinear interpolation, allow padding the image by 1 to allow events to fit:
    """
    if device is None:
        device = xs.device
    if interpolation == 'bilinear' and padding:
        img_size = (sensor_size[0]+1, sensor_size[1]+1)
    else:
        img_size = list(sensor_size)

    mask = torch.ones(xs.size(), device=device)
    if clip_out_of_range:
        zero_v = torch.tensor([0.], device=device)
        ones_v = torch.tensor([1.], device=device)
        clipx = img_size[1] if interpolation is None and padding==False else img_size[1]-1
        clipy = img_size[0] if interpolation is None and padding==False else img_size[0]-1
        mask = torch.where(xs>=clipx, zero_v, ones_v)*torch.where(ys>=clipy, zero_v, ones_v)

    img = (torch.ones(img_size)*default).to(device)
    if interpolation == 'bilinear' and xs.dtype is not torch.long and xs.dtype is not torch.long:
        pxs = (xs.floor()).float()
        pys = (ys.floor()).float()
        dxs = (xs-pxs).float()
        dys = (ys-pys).float()
        pxs = (pxs*mask).long()
        pys = (pys*mask).long()
        masked_ps = ps.squeeze()*mask
        interpolate_to_image(pxs, pys, dxs, dys, masked_ps, img)
    else:
        if xs.dtype is not torch.long:
            xs = xs.long().to(device)
        if ys.dtype is not torch.long:
            ys = ys.long().to(device)
        try:
            mask = mask.long().to(device)
            xs, ys = xs*mask, ys*mask
            img.index_put_((ys, xs), ps, accumulate=True)
        except Exception as e:
            print("Unable to put tensor {} positions ({}, {}) into {}. Range = {},{}".format(
                ps.shape, ys.shape, xs.shape, img.shape,  torch.max(ys), torch.max(xs)))
            raise e
    return img

def interpolate_to_image(pxs, pys, dxs, dys, weights, img):
    """
    Accumulate x and y coords to an image using bilinear interpolation
    """
    img.index_put_((pys,   pxs  ), weights*(1.0-dxs)*(1.0-dys), accumulate=True)
    img.index_put_((pys,   pxs+1), weights*dxs*(1.0-dys), accumulate=True)
    img.index_put_((pys+1, pxs  ), weights*(1.0-dxs)*dys, accumulate=True)
    img.index_put_((pys+1, pxs+1), weights*dxs*dys, accumulate=True)
    return img

def interpolate_to_derivative_img(pxs, pys, dxs, dys, d_img, w1, w2):
    """
    Accumulate x and y coords to an image using double weighted bilinear interpolation
    """
    for i in range(d_img.shape[0]):
        d_img[i].index_put_((pys,   pxs  ), w1[i] * (-(1.0-dys)) + w2[i] * (-(1.0-dxs)), accumulate=True)
        d_img[i].index_put_((pys,   pxs+1), w1[i] * (1.0-dys)    + w2[i] * (-dxs), accumulate=True)
        d_img[i].index_put_((pys+1, pxs  ), w1[i] * (-dys)       + w2[i] * (1.0-dxs), accumulate=True)
        d_img[i].index_put_((pys+1, pxs+1), w1[i] * dys          + w2[i] *  dxs, accumulate=True)

def image_to_event_weights(xs, ys, img):
    """
    Given an image and a set of event coordinates, get the pixel value
    of the image for each event using bilinear interpolation
    """
    clipx, clipy  = img.shape[1]-1, img.shape[0]-1
    mask = np.where(xs>=clipx, 0, 1)*np.where(ys>=clipy, 0, 1)

    pxs = np.floor(xs*mask).astype(int)
    pys = np.floor(ys*mask).astype(int)
    dxs = xs-pxs
    dys = ys-pys
    wxs, wys = 1.0-dxs, 1.0-dys

    weights =  img[pys, pxs]      *wxs*wys
    weights += img[pys, pxs+1]    *dxs*wys
    weights += img[pys+1, pxs]    *wxs*dys
    weights += img[pys+1, pxs+1]  *dxs*dys
    return weights*mask

def events_to_image_drv(xn, yn, pn, jacobian_xn, jacobian_yn,
        device=None, sensor_size=(180, 240), clip_out_of_range=True,
        interpolation='bilinear', padding=True, compute_gradient=False):
    """
    Method to turn event tensor to image. Allows for bilinear interpolation.
        :param xs: tensor of x coords of events
        :param ys: tensor of y coords of events
        :param ps: tensor of event polarities/weights
        :param device: the device on which the image is. If none, set to events device
        :param sensor_size: the size of the image sensor/output image
        :param clip_out_of_range: if the events go beyond the desired image size,
            clip the events to fit into the image
        :param interpolation: which interpolation to use. Options=None,'bilinear'
        :param if bilinear interpolation, allow padding the image by 1 to allow events to fit:
    """
    xt, yt, pt = torch.from_numpy(xn), torch.from_numpy(yn), torch.from_numpy(pn)
    xs, ys, ps, = xt.float(), yt.float(), pt.float()
    if compute_gradient:
        jacobian_x, jacobian_y = torch.from_numpy(jacobian_xn), torch.from_numpy(jacobian_yn)
        jacobian_x, jacobian_y = jacobian_x.float(), jacobian_y.float()
    if device is None:
        device = xs.device
    if padding:
        img_size = (sensor_size[0]+1, sensor_size[1]+1)
    else:
        img_size = sensor_size

    mask = torch.ones(xs.size())
    if clip_out_of_range:
        zero_v = torch.tensor([0.])
        ones_v = torch.tensor([1.])
        clipx = img_size[1] if interpolation is None and padding==False else img_size[1]-1
        clipy = img_size[0] if interpolation is None and padding==False else img_size[0]-1
        mask = torch.where(xs>=clipx, zero_v, ones_v)*torch.where(ys>=clipy, zero_v, ones_v)

    pxs = xs.floor()
    pys = ys.floor()
    dxs = xs-pxs
    dys = ys-pys
    pxs = (pxs*mask).long()
    pys = (pys*mask).long()
    masked_ps = ps*mask
    img = torch.zeros(img_size).to(device)
    interpolate_to_image(pxs, pys, dxs, dys, masked_ps, img)

    if compute_gradient:
        d_img = torch.zeros((2, *img_size)).to(device)
        w1 = jacobian_x*masked_ps
        w2 = jacobian_y*masked_ps
        interpolate_to_derivative_img(pxs, pys, dxs, dys, d_img, w1, w2)
        d_img = d_img.numpy()
    else:
        d_img = None
    return img.numpy(), d_img

def events_to_timestamp_image(xn, yn, ts, pn,
        device=None, sensor_size=(180, 240), clip_out_of_range=True,
        interpolation='bilinear', padding=True, normalize_timestamps=True):
    """
    Method to generate the average timestamp images from 'Zhu19, Unsupervised Event-based Learning 
    of Optical Flow, Depth, and Egomotion'. This method does not have known derivative.
    Parameters
    ----------
    xs : list of event x coordinates 
    ys : list of event y coordinates 
    ts : list of event timestamps 
    ps : list of event polarities 
    device : the device that the events are on
    sensor_size : the size of the event sensor/output voxels
    clip_out_of_range: if the events go beyond the desired image size,
       clip the events to fit into the image
    interpolation: which interpolation to use. Options=None,'bilinear'
    padding: if bilinear interpolation, allow padding the image by 1 to allow events to fit:
    Returns
    -------
    img_pos: timestamp image of the positive events
    img_neg: timestamp image of the negative events 
    """

    t0 = ts[0]
    xt, yt, ts, pt = torch.from_numpy(xn), torch.from_numpy(yn), torch.from_numpy(ts-t0), torch.from_numpy(pn)
    xs, ys, ts, ps = xt.float(), yt.float(), ts.float(), pt.float()
    zero_v = torch.tensor([0.])
    ones_v = torch.tensor([1.])
    if device is None:
        device = xs.device
    if padding:
        img_size = (sensor_size[0]+1, sensor_size[1]+1)
    else:
        img_size = sensor_size

    mask = torch.ones(xs.size())
    if clip_out_of_range:
        clipx = img_size[1] if interpolation is None and padding==False else img_size[1]-1
        clipy = img_size[0] if interpolation is None and padding==False else img_size[0]-1
        mask = torch.where(xs>=clipx, zero_v, ones_v)*torch.where(ys>=clipy, zero_v, ones_v)

    pos_events_mask = torch.where(ps>0, ones_v, zero_v)
    neg_events_mask = torch.where(ps<=0, ones_v, zero_v)
    normalized_ts = (ts-ts[0])/(ts[-1]+1e-6) if normalize_timestamps else ts
    pxs = xs.floor()
    pys = ys.floor()
    dxs = xs-pxs
    dys = ys-pys
    pxs = (pxs*mask).long()
    pys = (pys*mask).long()
    masked_ps = ps*mask

    pos_weights = normalized_ts*pos_events_mask
    neg_weights = normalized_ts*neg_events_mask
    img_pos = torch.zeros(img_size).to(device)
    img_pos_cnt = torch.ones(img_size).to(device)
    img_neg = torch.zeros(img_size).to(device)
    img_neg_cnt = torch.ones(img_size).to(device)

    interpolate_to_image(pxs, pys, dxs, dys, pos_weights, img_pos)
    interpolate_to_image(pxs, pys, dxs, dys, pos_events_mask, img_pos_cnt)
    interpolate_to_image(pxs, pys, dxs, dys, neg_weights, img_neg)
    interpolate_to_image(pxs, pys, dxs, dys, neg_events_mask, img_neg_cnt)

    img_pos, img_pos_cnt = img_pos.numpy(), img_pos_cnt.numpy()
    img_pos_cnt[img_pos_cnt==0] = 1
    img_neg, img_neg_cnt = img_neg.numpy(), img_neg_cnt.numpy()
    img_neg_cnt[img_neg_cnt==0] = 1
    img_pos, img_neg = img_pos/img_pos_cnt, img_neg/img_neg_cnt
    return img_pos, img_neg

def events_to_timestamp_image_torch(xs, ys, ts, ps,
        device=None, sensor_size=(180, 240), clip_out_of_range=True,
        interpolation='bilinear', padding=True, timestamp_reverse=False):
    """
    Method to generate the average timestamp images from 'Zhu19, Unsupervised Event-based Learning 
    of Optical Flow, Depth, and Egomotion'. This method does not have known derivative.
    Parameters
    ----------
    xs : list of event x coordinates 
    ys : list of event y coordinates 
    ts : list of event timestamps 
    ps : list of event polarities 
    device : the device that the events are on
    sensor_size : the size of the event sensor/output voxels
    clip_out_of_range: if the events go beyond the desired image size,
       clip the events to fit into the image
    interpolation: which interpolation to use. Options=None,'bilinear'
    padding: if bilinear interpolation, allow padding the image by 1 to allow events to fit:
    timestamp_reverse: reverse the timestamps of the events, for backward warp
    Returns
    -------
    img_pos: timestamp image of the positive events
    img_neg: timestamp image of the negative events 
    """
    if device is None:
        device = xs.device
    xs, ys, ps, ts = xs.squeeze(), ys.squeeze(), ps.squeeze(), ts.squeeze()
    if padding:
        img_size = (sensor_size[0]+1, sensor_size[1]+1)
    else:
        img_size = sensor_size
    zero_v = torch.tensor([0.], device=device)
    ones_v = torch.tensor([1.], device=device)

    mask = torch.ones(xs.size(), device=device)
    if clip_out_of_range:
        clipx = img_size[1] if interpolation is None and padding==False else img_size[1]-1
        clipy = img_size[0] if interpolation is None and padding==False else img_size[0]-1
        mask = torch.where(xs>=clipx, zero_v, ones_v)*torch.where(ys>=clipy, zero_v, ones_v)

    pos_events_mask = torch.where(ps>0, ones_v, zero_v)
    neg_events_mask = torch.where(ps<=0, ones_v, zero_v)
    epsilon = 1e-6
    if timestamp_reverse:
        normalized_ts = ((-ts+ts[-1])/(ts[-1]-ts[0]+epsilon)).squeeze()
    else:
        normalized_ts = ((ts-ts[0])/(ts[-1]-ts[0]+epsilon)).squeeze()
    pxs = xs.floor().float()
    pys = ys.floor().float()
    dxs = (xs-pxs).float() 
    dys = (ys-pys).float()
    pxs = (pxs*mask).long()
    pys = (pys*mask).long()
    masked_ps = ps*mask

    pos_weights = (normalized_ts*pos_events_mask).float()
    neg_weights = (normalized_ts*neg_events_mask).float()
    img_pos = torch.zeros(img_size).to(device)
    img_pos_cnt = torch.ones(img_size).to(device)
    img_neg = torch.zeros(img_size).to(device)
    img_neg_cnt = torch.ones(img_size).to(device)

    interpolate_to_image(pxs, pys, dxs, dys, pos_weights, img_pos)
    interpolate_to_image(pxs, pys, dxs, dys, pos_events_mask, img_pos_cnt)
    interpolate_to_image(pxs, pys, dxs, dys, neg_weights, img_neg)
    interpolate_to_image(pxs, pys, dxs, dys, neg_events_mask, img_neg_cnt)

    # Avoid division by 0
    img_pos_cnt[img_pos_cnt==0] = 1
    img_neg_cnt[img_neg_cnt==0] = 1
    img_pos = img_pos.div(img_pos_cnt)
    img_neg = img_neg.div(img_neg_cnt)
    return img_pos, img_neg #/img_pos_cnt, img_neg/img_neg_cnt

class TimestampImage:

    def __init__(self, sensor_size):
        self.sensor_size = sensor_size
        self.num_pixels = sensor_size[0]*sensor_size[1]
        self.image = np.ones(sensor_size)

    def set_init(self, value):
        self.image = np.ones_like(self.image)*value

    def add_event(self, x, y, t, p):
        self.image[int(y), int(x)] = t

    def add_events(self, xs, ys, ts, ps):
        for x, y, t in zip(xs, ys, ts):
            self.add_event(x, y, t, 0)

    def get_image(self):
        sort_args = rankdata(self.image, method='dense')
        sort_args = sort_args-1
        sort_args = sort_args.reshape(self.sensor_size)
        sort_args = sort_args/np.max(sort_args)
        return sort_args

class EventImage:

    def __init__(self, sensor_size):
        self.sensor_size = sensor_size
        self.num_pixels = sensor_size[0]*sensor_size[1]
        self.image = np.ones(sensor_size)

    def add_event(self, x, y, t, p):
        self.image[int(y), int(x)] += p

    def add_events(self, xs, ys, ts, ps):
        for x, y, t in zip(xs, ys, ts):
            self.add_event(x, y, t, 0)

    def get_image(self):
        mn, mx = np.min(self.image), np.max(self.image)
        norm_img = (self.image-mn)/(mx-mn)
        return norm_img
