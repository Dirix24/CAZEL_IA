#include <Servo.h>
#define TRIG 7
#define ECHO 8
const int MOTOR_A = 5;
int led = 13;
Servo brazo;
void setup() {
  Serial.begin(9600);
  pinMode(TRIG, OUTPUT); pinMode(ECHO, INPUT);
  pinMode(MOTOR_A, OUTPUT); pinMode(led, OUTPUT);
  brazo.attach(9);
}
void loop() {
  if (Serial.available()) { String cmd = Serial.readStringUntil('\n'); if (cmd == "avanzar") analogWrite(MOTOR_A, 200); }
  digitalWrite(led, HIGH);
  long t = pulseIn(ECHO, HIGH);
  int luz = analogRead(A0);
}
