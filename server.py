import sys
import pprint
import uuid
import logging
import json
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

import gevent
from gevent.server import StreamServer

import fastmc.auth
import fastmc.proto

class Server(object):

    maxPlayers = 64;

    def __init__(self):
        self.token = fastmc.auth.generate_challenge_token()
        self.server_id = fastmc.auth.generate_server_id()
        self.key = fastmc.auth.generate_key_pair()
        self.loadConfig()

    def loadConfig(self):
        with open("config.txt") as f:
            for line in f:
                if(line.startswith("Max Players:")):
                    self.maxPlayers = int(line.split(":")[1])

    def handle_pkt(self, pkt):
        print pkt
        print

        if self.reader.state == fastmc.proto.HANDSHAKE:
            if pkt.id == 0x00:
                self.reader.switch_state(pkt.state)
                self.writer.switch_state(pkt.state)
        elif self.reader.state == fastmc.proto.STATUS:
            if pkt.id == 0x00:
                out_buf = fastmc.proto.WriteBuffer()
                self.writer.write(out_buf, 0x00, response={
                    "version": {
                        "name": self.reader.protocol.name,
                        "protocol": self.reader.protocol.version,
                    },
                    "players": {
                        "max": self.maxPlayers,
                        "online": 0,
                    },  
                    "description": {
                        "text":"fastmc",
                        "color": "red",
                        "extra": [{
                            "text": " Test Server",
                            "color": "blue",
                        }]
                    },
                })
                self.sock.send(out_buf)
            elif pkt.id == 0x01:
                out_buf = fastmc.proto.WriteBuffer()
                self.writer.write(out_buf, 0x01, 
                    time=pkt.time
                )
                self.sock.send(out_buf)
        elif self.reader.state == fastmc.proto.LOGIN:
            if pkt.id == 0x00:
                out_buf = fastmc.proto.WriteBuffer()

                self.player_ign = pkt.name

                self.writer.write(out_buf, 0x01, 
                    server_id = self.server_id,
                    public_key = fastmc.auth.encode_public_key(self.key),
                    challenge_token = self.token,
                )
                self.sock.send(out_buf)
            elif pkt.id == 0x01:
                decrypted_token = fastmc.auth.decrypt_with_private_key(
                    pkt.response_token, self.key
                )

                if decrypted_token != self.token:
                    raise Exception("Token verification failed")

                shared_secret = fastmc.auth.decrypt_with_private_key(
                    pkt.shared_secret, self.key
                )

                self.sock.set_cipher(
                    fastmc.auth.generated_cipher(shared_secret),
                    fastmc.auth.generated_cipher(shared_secret),
                )

                server_hash = fastmc.auth.make_server_hash(
                    server_id = self.server_id,
                    shared_secret = shared_secret,
                    key = self.key,
                )

                check = fastmc.auth.check_player(self.player_ign, server_hash)
                if not check:
                    raise Exception("Cannot verify your username. Sorry.")

                print
                print "Player information from Mojang"
                print "---------------------------------------"
                pprint.pprint(check)

                print
                print "Decoded Property Values"
                print "---------------------------------------"
                pprint.pprint(json.loads(check['properties'][0]['value'].decode('base64')))

                out_buf = fastmc.proto.WriteBuffer()

                # setting the threshold higher is probably a good idea
                # for a real server. Lets keep it at 64 for this demo, so
                # it can actually compress the disconnect message.
                threshold = 64
                self.writer.write(out_buf, 0x03,
                    threshold = threshold,
                )

                self.reader.set_compression_threshold(threshold)
                self.writer.set_compression_threshold(threshold)

                self.writer.write(out_buf, 0x02, 
                    uuid = str(uuid.UUID(check['id'])),
                    username = self.player_ign,
                )

                self.reader.switch_state(fastmc.proto.PLAY)
                self.writer.switch_state(fastmc.proto.PLAY)

                self.sock.send(out_buf)
                print "%s logged in" % self.player_ign

                out_buf = fastmc.proto.WriteBuffer()
                self.writer.write(out_buf, 0x40, 
                    reason = {"text": "", "extra": [{
                        "color": "yellow",
                        "text": "That's all. There's no world on this server.",
                    }, {
                        "color": "red",
                        "text": " Thanks for testing!",
                    }]},
                )
                self.sock.send(out_buf)

        elif self.reader.state == fastmc.proto.PLAY:
            # ready to receive game play packets from client
            pass

    def reader(self, sock):
        protocol_version = 47

        self.sock = fastmc.proto.MinecraftSocket(sock)
        self.reader, self.writer = fastmc.proto.Endpoint.server_pair(protocol_version)

        in_buf = fastmc.proto.ReadBuffer()
        while 1:
            data = self.sock.recv()
            if not data:
                break
            in_buf.append(data)
            while 1:
                pkt, pkt_raw = self.reader.read(in_buf)
                if pkt is None:
                    break
                self.handle_pkt(pkt)

        print "client disconnected"
        sock.close()


def handle(sock, addr):
    gevent.spawn(Server().reader, sock)

listener = StreamServer(('127.0.0.1', 25565), handle)
listener.start()
listener.serve_forever()
