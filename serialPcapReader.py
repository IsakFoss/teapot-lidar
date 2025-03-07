from pcapReader import PcapReader
from tqdm import tqdm
from sbetParser import SbetParser
import numpy as np

class SerialPcapReader:

    def __init__(self, pcap_paths, meta_data_paths, skip_frames = 0, sbet_path = None):
        self.readers = [PcapReader(x[0], x[1], skip_frames, sbet_path=sbet_path) for x in zip(pcap_paths, meta_data_paths)]
        self.current_reader_index = 0
        self.max_distance = None
        self._set_metadata()

    def count_frames(self, show_progress):
        return sum([x.count_frames(False) for x in tqdm(self.readers, ascii=True, desc="Counting frames", disable=not show_progress)])

    def reset(self):
        for reader in self.readers:
            reader.reset()
        self.current_reader_index = 0
        self._set_metadata()

    def _next_reader(self):
        self.current_reader_index += 1
        self._set_metadata()

    def _set_metadata(self):
        self.pcap_path = None if self.current_reader_index >= len(self.readers) else self.readers[self.current_reader_index].pcap_path

    def skip_and_get(self, iterator):

        if self.current_reader_index >= len(self.readers):
            return None

        self.readers[self.current_reader_index].max_distance = self.max_distance
        frame = self.readers[self.current_reader_index].skip_and_get(iterator)
        if frame is None:
            self._next_reader()
            return self.skip_and_get(iterator)

        return frame

    def get_coordinates(self, rotate=True):
        """Returns a list of coordinates (SbetRow) corresponding to each LidarPacket in the current Pcap file."""

        coordinates = []
        self.readers_first_coordinate_index = []
        
        for reader in self.readers:
            self.readers_first_coordinate_index.append(len(coordinates))
            coordinates.extend(reader.get_coordinates(False))
        
        return SbetParser.rotate_points(coordinates, coordinates[0].heading - np.pi / 2) if rotate else coordinates

    def get_current_frame_index(self):
        ix = 0

        for i, reader in enumerate(self.readers):
            if reader == self.readers[self.current_reader_index]:
                ix += reader.get_current_frame_index()
                break
            else:
                ix += self.readers_first_coordinate_index[i]

        return ix

    def print_info(self, frame_index = None, printFunc = print):
        for reader in self.readers:
            reader.print_info(frame_index, printFunc)

    def remove_vehicle(self, frame, cloud = None):
        return self.readers[0].remove_vehicle(frame, cloud)

    def next_frame(self, remove_vehicle:bool = False, timer = None):
        if self.current_reader_index >= len(self.readers):
            return None

        self.readers[self.current_reader_index].max_distance = self.max_distance
        frame = self.readers[self.current_reader_index].next_frame(remove_vehicle, timer)
        if frame is None:
            self._next_reader()
            return self.next_frame(remove_vehicle, timer)

        return frame

    def read_all_frames(self, remove_vehicle:bool = False):

        frames = []
        while True:
            frame = self.next_frame(remove_vehicle)
            if frame is None:
                return frames
            frames.append(frame)