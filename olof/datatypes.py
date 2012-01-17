#from olof.locationprovider import Project, Location

import time

server = None

def unixtime(timestamp, format='%Y%m%d-%H%M%S-%Z'):
    return time.mktime(time.strptime(timestamp, format))

class Location(object):
    def __init__(self, name, id, lat, lon):
        self.name = name
        self.id = id
        self.description = None
        self.lat = lat
        self.lon = lon

        self.project = None
        self.sensors = {}

    def add_sensor(self, sensor):
        if not sensor.mac in self.sensors:
            self.sensors[sensor.mac] = sensor
            sensor.location = self
            if sensor.lat == None or sensor.lon == None:
                sensor.lat = self.lat
                sensor.lon = self.lon

    def compare(self, location):
        if False in [self.__dict__[i] == location.__dict__[i] for i in [
            'id', 'description', 'lat', 'lon']]:
            # Something changed in the scanner details

            args = {'hostname': str(location.name),
                    'id': str(location.id),
                    'description': str(location.description)}

            if None not in [location.lon, location.lat] and location.sensors.values()[0].start != None:
                args['coordinates'] = (float(location.lon), float(location.lat))
                args['timestamp'] = location.sensors.values()[0].start
            elif None in [location.lon, location.lat] or location.sensors.values()[0].end != None:
                args['coordinates'] = None
                args['timestamp'] = location.sensors.values()[0].end

            # Push scanner update
            args['module'] = 'scanner'
            print "LU 3"
            for p in server.plugins:
                p.locationUpdate(**args)
                p.newLocationUpdate(location.name, 'scanner', location)

            # Push sensor updates
            for sensor in location.sensors.values():
                args['module'] = str(sensor.mac)
                if None in [sensor.lat, sensor.lon]:
                    args['coordinates'] = None
                else:
                    args['coordinates'] = (float(sensor.lon), float(sensor.lat))
                print "LU 4"
                for p in server.plugins:
                    p.locationUpdate(**args)
                    p.newLocationUpdate(location.name, 'sensor', sensor)

        else:
            # Scanner details identical, compare sensors
            update = False

            for sensor in self.sensors:
                if sensor in location.sensors:
                    if not self.sensors[sensor] == location.sensors[sensor]:
                        update = True
                        print "SU 1"
                else:
                    update = True
                    print "SU 2"

            for sensor in location.sensors:
                if sensor in self.sensors:
                    if not self.sensors[sensor] == location.sensors[sensor]:
                        update = True
                        print "SU 3"
                else:
                    update = True
                    print "SU 4"

            if update:
                args = {'hostname': str(location.name),
                        'id': str(location.id),
                        'description': str(location.description)}

                if None not in [location.lon, location.lat] and location.sensors.values()[0].start != None:
                    args['coordinates'] = (float(location.lon), float(location.lat))
                    args['timestamp'] = location.sensors.values()[0].start
                elif None in [location.lon, location.lat] or location.sensors.values()[0].end != None:
                    args['coordinates'] = None
                    args['timestamp'] = location.sensors.values()[0].end

                # Push scanner update
                args['module'] = 'scanner'
                print "LU 5"
                for p in server.plugins:
                    p.locationUpdate(**args)
                    p.newLocationUpdate(location.name, 'scanner', location)

                # Push sensor updates
                for sensor in location.sensors.values():
                    args['module'] = str(sensor.mac)
                    if None in [sensor.lat, sensor.lon]:
                        args['coordinates'] = None
                    else:
                        args['coordinates'] = (float(sensor.lon), float(sensor.lat))
                    print "LU 6"
                    for p in server.plugins:
                        p.locationUpdate(**args)
                        p.newLocationUpdate(location.name, 'sensor', sensor)

class Sensor(object):
    def __init__(self, mac):
        self.mac = mac
        self.location = None
        self.lat = None
        self.lon = None

        self.start = None
        self.end = None

    def __eq__(self, sensor):
        return False not in [self.__dict__[i] == sensor.__dict__[i] for i in [
            'mac', 'lat', 'lon', 'start', 'end']]

class Project(object):
    def __init__(self, name):
        self.name = name

        self.active = True
        self.disabled_plugins = []

        self.locations = {}

        self.start = None
        self.end = None

    def is_active(self):
        if self.active == False:
            return False

        elif self.active == True:
            now = int(time.time())

            if self.start != None and self.end == None:
                return now >= self.start
            elif self.start == None and self.end != None:
                return now < self.end
            elif self.start != None and self.end != None:
                if self.end <= self.start:
                    raise ValueError("Start should predate end.")
                return self.start <= now < self.end
            else:
                return True

    def add_location(self, location):
        self.locations[location.name] = location
        location.project = self


#DEPRECATED
class Projects(object):
    def __init__(self, server, location_provider):
        self.server = server
        self.locations = location_provider.locations
        self.projects = location_provider.projects

    def list_projects(self):
        return sorted([p.name for p in self.projects])

    def get_project(self, projectname):
        return self.projects.get(projectname, None)

    def hostname_enabled(self, hostname):
        if hostname in self.locations:
            if Location.Project in self.locations[hostname]:
                return self.enabled(self.locations[hostname][Location.Project])
            else:
                return False
        else:
            return False

