from open3dVisualizer import Open3DVisualizer
from navigatorBase import NavigatorBase
from plotter import Plotter
import numpy as np
import os
from tqdm import tqdm
import open3d as o3d
from datetime import datetime
import copy
import json

class AbsoluteLidarNavigator(NavigatorBase):

    def __init__(self, args):
        """Initialize an AbsoluteLidarNavigator by reading metadata and setting
        up a package source from the pcap file.
        """
        self.load_point_cloud(args.point_cloud)

        NavigatorBase.__init__(self, args, 0)

    def load_point_cloud(self, path):
        if path.endswith(".cloud"):
            with open(path, "r") as outfile:
                data = json.load(outfile)
            self.full_point_cloud_offset = np.array(data["offset"])
            self.full_cloud = o3d.io.read_point_cloud(data["cloud"])

            print("    > Offset")
            print("    >", self.full_point_cloud_offset)
            self.print_cloud_info("Full cloud moved", self.full_cloud, "    ")
        else:
            print("Preparing point cloud:")
            print("    > Reading ...")
            self.full_cloud = o3d.io.read_point_cloud(path)
            print("    > Moving")
            self.print_cloud_info("Full cloud original", self.full_cloud, "    ")
            points = np.asarray(self.full_cloud.points)
            self.full_point_cloud_offset = np.amin(points, axis=0)
            self.full_point_cloud_offset += (np.amax(points, axis=0) - self.full_point_cloud_offset) / 2
            print("    > Offset")
            print("    >", self.full_point_cloud_offset)
            points -= self.full_point_cloud_offset
            self.full_cloud = o3d.geometry.PointCloud()
            self.full_cloud.points = o3d.utility.Vector3dVector(points)
            self.print_cloud_info("Full cloud moved", self.full_cloud, "    ")
            print("    > Estimating normals")
            self.full_cloud.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.1, max_nn=30))
        
            # Hard-coded lines for saving a pre-processed point cloud (that is already moved to origo and has normals) with an accompanying .cloud file.
            o3d.io.write_point_cloud("G:\\2021-10-21 - Kartverket, LIDAR\\validation\\Lillehammer\\Punktsky_211021\\assembled-moved-with-normals.pcd", self.full_cloud, compressed=False)
            with open("G:\\2021-10-21 - Kartverket, LIDAR\\validation\\Lillehammer\\Punktsky_211021\\assembled-moved-with-normals.cloud", "w") as outfile:
                json.dump({ "offset": self.full_point_cloud_offset.tolist(), "cloud": "G:\\2021-10-21 - Kartverket, LIDAR\\validation\\Lillehammer\\Punktsky_211021\\assembled-moved-with-normals.pcd" }, outfile)
        
        self.full_cloud.paint_uniform_color([0.3, 0.6, 1.0])

        print("    > Cloud read")

    def navigate_through_file(self):
        """ Runs through each frame in the file. For each pair of frames, use NICP
        to align the frames, then merge them and downsample the result. The transformation
        matrix from the NICP operation is used to calculate the movement of the center point
        (the vehicle) between the frames. Each movement is stored, and drawn as a red line
        to show the driving route.
        """
        
        self.timer.reset()
        self.skip_initial_frames()

        # Initialize the list of movements as well as the merged frame, and the first 
        # source frame.
        self.movements = []

        self.movement_path = o3d.geometry.LineSet(
            points = o3d.utility.Vector3dVector([]), lines=o3d.utility.Vector2iVector([])
        )

        if args.sbet is not None:

            # Read the coordinates from all frames in the PCAP file(s).
            # We set the rotate-argument to False, since we're working with
            # the same coordinate system here -- both the georeferenced point cloud
            # and the actual coordinates of the frames are in UTM, and there is
            # therefore no need to rotate them like it is in the visual odometry
            # based navigator.
            self.actual_coordinates = self.reader.get_coordinates(False)

            # Translate all coordinates towards origo with the same offset as
            # the point cloud.
            for c in self.actual_coordinates:
                c.translate(self.full_point_cloud_offset)
                c.translate([0, 0, 40])

            self.current_coordinate = self.actual_coordinates[0].clone()
            self.initial_coordinate = self.actual_coordinates[0].clone()

            self.actual_movement_path = o3d.geometry.LineSet(
                points = o3d.utility.Vector3dVector([[p.x, p.y, p.alt] for p in self.actual_coordinates]), 
                lines = o3d.utility.Vector2iVector([[i, i+1] for i in range(len(self.actual_coordinates) - 1)])
            )
            self.actual_movement_path.paint_uniform_color([0, 0, 1])

        self.vis = None
        self.merged_frame = o3d.geometry.PointCloud()
        plot = Plotter(self.preview_always)

        # Enumerate all frames until the end of the file and run the merge operation.
        for i in tqdm(range(0, self.frame_limit), total=self.frame_limit, ascii=True, initial=0, **self.tqdm_config):
            
            try:

                if self.merge_next_frame(plot):

                    if self.vis is None:
                        # Initialize the visualizer
                        self.vis = Open3DVisualizer()

                        if self.preview_always:
                            # Initiate non-blocking visualizer window
                            self.vis.refresh_non_blocking()

                            # Show the first frame and reset the view
                            self.vis.show_frame(self.merged_frame)
                            self.vis.set_follow_vehicle_view(self.movements[-1])

                            self.check_save_screenshot(0, True)

                        self.time("navigation preparations")

                    # Refresh the non-blocking visualization
                    if self.preview_always:
                        self.vis.refresh_non_blocking()
                        self.vis.set_follow_vehicle_view(self.movements[-1])
                        self.time("visualization refresh")

                        self.check_save_screenshot(i)

                    plot.step(self.preview_always)
                    self.time("plot step")

            except KeyboardInterrupt:
                
                print("")
                print("********************************")
                print("Process aborted. Results so far:")
                print("********************************")
                plot.print_summary(self.timer)
                print("")
                print("")

                raise

        # Ensure the final cloud has been downsampled
        self.ensure_merged_frame_is_downsampled()

        # When everything is finished, print a summary, and save the point cloud and debug data.
        if self.preview_at_end:
            plot.update()

        self.print_cloud_info("Merged frame", self.merged_frame)
        self.print_cloud_info("Full cloud", self.full_cloud)
        self.draw_registration_result(self.merged_frame, self.full_cloud)

        results = self.get_results(plot)

        if self.save_path is not None:
            filenameBase = self.save_path.replace("[time]", datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f%z'))
            filenameBase = filenameBase.replace("[pcap]", os.path.basename(self.reader.pcap_path).replace(".pcap", ""))
            self.ensure_dir(filenameBase)
            plot.save_plot(filenameBase + "_plot.png")
            self.save_cloud_as_las(filenameBase + "_cloud.laz", self.merged_frame)
            o3d.io.write_point_cloud(filenameBase + "_cloud.pcd", self.merged_frame, compressed=True)

            self.time("results saving")
            
            self.save_data(filenameBase + "_data.json", results)
        
        if self.print_summary_at_end:
            plot.print_summary(self.timer)

        # Then continue showing the visualization in a blocking way until the user stops it.
        if self.preview_at_end:
            self.vis.show_frame(self.merged_frame)
            self.vis.remove_geometry(self.movement_path)
            self.vis.add_geometry(self.movement_path)
            self.vis.reset_view()

            self.vis.run()

        plot.destroy()

        return results

    def draw_registration_result(self, source, target):
        source_temp = copy.deepcopy(source)
        target_temp = copy.deepcopy(target)
        source_temp.paint_uniform_color([1, 0.706, 0])
        target_temp.paint_uniform_color([0, 0.651, 0.929])
        o3d.visualization.draw_geometries([source_temp, target_temp])

    def merge_next_frame(self, plot):
        """ Reads the next frame, aligns it with the previous frame, merges them together
        to create a 3D model, and tracks the movement between frames.
        """

        # Fetch the next frame
        frame = self.reader.next_frame(self.remove_vehicle, self.timer)

        # The following lines are a temporary debugging visualization
        self.vis = Open3DVisualizer()
        self.vis.show_frame(self.full_cloud)
        self.vis.add_geometry(self.actual_movement_path)
        self.vis.reset_view()
        self.vis.run()
        afdsajhuiCRASH

        # If it is empty, that (usually) means we have reached the end of
        # the file. Return False to stop the loop.
        if frame is None:
            return False

        # Estimate normals for the target frame (the source frame will always have
        # normals from the previous step).
        frame.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.1, max_nn=30))

        self.time("normal estimation")

        # Run the alignment
        reg = self.matcher.match(frame, self.full_cloud, 10, None)
        self.check_save_frame_pair(self.full_cloud, frame, reg)

        registration_time = self.time("registration")

        # Extract the translation part from the transformation array
        movement = reg.transformation[:3,3]
        
        plot.timeUsages.append(registration_time)
        plot.rmses.append(reg.inlier_rmse)
        plot.fitnesses.append(reg.fitness)
        plot.distances.append(np.sqrt(np.dot(movement, movement)))

        # Append the newest movement
        self.movements.append(movement)

        # Append the new movement to the path
        self.movement_path.points.append(reg.transformation[:3,3])
        #self.movement_path = self.movement_path.transform(transformation)

        # Add the new line
        if len(self.movements) == 2:
            self.vis.add_geometry(self.movement_path)
        if len(self.movements) >= 2:
            self.movement_path.lines.append([len(self.movements) - 2, len(self.movements) - 1])
            self.movement_path.paint_uniform_color([1, 0, 0])
            self.vis.update_geometry(self.movement_path)

        self.time("book keeping")

        # Transform the frame to fit the merged point cloud
        #self.merged_frame = self.merged_frame

        self.time("frame transformation")

        self.previous_transformation = reg.transformation

        # Combine the points from the merged visualization with the points from the next frame
        transformed_frame = copy.deepcopy(frame)
        print("")
        print("")
        print("Movement", movement)
        print("Transformation:")
        print(reg.transformation)
        self.print_cloud_info("Frame", frame)
        transformed_frame.transform(reg.transformation)
        self.print_cloud_info("Transformed frame", transformed_frame)
        self.merged_frame += transformed_frame
        self.merged_frame_is_dirty = True

        self.time("cloud merging")

        # Downsample the merged visualization to make it faster to work with.
        # Otherwise it would grow extremely large, as it would contain all points
        # from all processed point clouds.
        # Don't do this on every frame, as it takes a lot of time.
        self.downsample_timer -= 1
        if self.downsample_timer <= 0:
            self.ensure_merged_frame_is_downsampled()
            self.downsample_timer = self.downsample_cloud_after_frames

        # Update the visualization
        if self.preview_always and self.vis is not None:
            self.vis.show_frame(self.merged_frame, True)

            self.time("visualization")

        # Return True to let the loop continue to the next frame.
        return True
        

if __name__ == "__main__":

    parser = NavigatorBase.create_parser()

    parser.add_argument('--point-cloud', type=str, required=True, help="An Open3D point cloud file to use for absolute navigation.")
    
    args = NavigatorBase.add_standard_and_parse_args(parser)

    # Create and start a visualization
    navigator = AbsoluteLidarNavigator(args)
    navigator.print_summary_at_end = True
    navigator.navigate_through_file()