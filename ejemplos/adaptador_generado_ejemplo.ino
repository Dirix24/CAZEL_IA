// ============================================================
// CAZEL IA - ADAPTADOR (generado automáticamente)
// REVÍSALO antes de subirlo: comprueba que cada pin es el correcto.
// CAZEL no sube código a tu placa; súbelo tú con el Arduino IDE.
// ============================================================
#include <Servo.h>

const char NOMBRE[] = "brazo_uno";
const long BAUDIOS = 9600;
// Si no llega ninguna orden en este tiempo, las salidas PWM y digitales se apagan.
const unsigned long WATCHDOG_MS = 3000;

Servo servo_9;           // pin 9
const int PIN_PWM_5 = 5;
const int PIN_13 = 13;
const int PIN_ANALOGICO_A0 = A0;
const int PIN_TRIG = 7;
const int PIN_ECHO = 8;

char linea[40];
byte largo = 0;
unsigned long ultimaOrden = 0;
bool salidasActivas = false;

void pararTodo() {
  analogWrite(PIN_PWM_5, 0);
  digitalWrite(PIN_13, LOW);
  salidasActivas = false;
}

void setup() {
  Serial.begin(BAUDIOS);
  pinMode(PIN_PWM_5, OUTPUT);
  pinMode(PIN_13, OUTPUT);
  servo_9.attach(9);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  pararTodo();
}

void responderAyuda() {
  Serial.print("CAZEL 1 "); Serial.println(NOMBRE);
  Serial.println("ORDEN servo_9 grados:0:180");
  Serial.println("ORDEN pwm_5 valor:0:255");
  Serial.println("ORDEN pin_13 estado:0:1");
  Serial.println("ORDEN parar");
  Serial.println("LECTURA analogico_a0 0-1023");
  Serial.println("LECTURA distancia cm");
  Serial.println("FIN");
}

long leerDistanciaCm() {
  digitalWrite(PIN_TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  long us = pulseIn(PIN_ECHO, HIGH, 30000UL);   // tope: ~5 m
  if (us == 0) return -1;                       // sin eco
  return us / 58;
}

void procesar(char *texto) {
  char *nombre = strtok(texto, " ");
  if (nombre == NULL) return;
  char *valorTxt = strtok(NULL, " ");
  long valor = valorTxt ? atol(valorTxt) : 0;

  if (strcmp(nombre, "AYUDA") == 0) { responderAyuda(); return; }
  if (strcmp(nombre, "PARAR") == 0 || strcmp(nombre, "parar") == 0) { pararTodo(); Serial.println("OK"); return; }
  if (strcmp(nombre, "LEER") == 0) {
    if (valorTxt == NULL) { Serial.println("ERR falta la lectura"); return; }
    if (strcmp(valorTxt, "analogico_a0") == 0) { Serial.print("VAL "); Serial.println(analogRead(PIN_ANALOGICO_A0)); return; }
    else if (strcmp(valorTxt, "distancia") == 0) {
      long d = leerDistanciaCm();
      if (d < 0) Serial.println("ERR sin eco");
      else { Serial.print("VAL "); Serial.println(d); }
      return;
    }
    Serial.println("ERR lectura desconocida");
    return;
  }

  if (valorTxt == NULL) { Serial.println("ERR falta el valor"); return; }
  ultimaOrden = millis();
  if (strcmp(nombre, "servo_9") == 0) {
    if (valor < 0 || valor > 180) { Serial.println("ERR fuera de rango"); return; }
    servo_9.write((int)valor); Serial.println("OK"); return;
  }
  if (strcmp(nombre, "pwm_5") == 0) {
    if (valor < 0 || valor > 255) { Serial.println("ERR fuera de rango"); return; }
    analogWrite(PIN_PWM_5, (int)valor); salidasActivas = true; Serial.println("OK"); return;
  }
  if (strcmp(nombre, "pin_13") == 0) {
    if (valor != 0 && valor != 1) { Serial.println("ERR fuera de rango"); return; }
    digitalWrite(PIN_13, valor ? HIGH : LOW); salidasActivas = true; Serial.println("OK"); return;
  }
  Serial.println("ERR orden desconocida");
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') { linea[largo] = 0; procesar(linea); largo = 0; }
    else if (largo < sizeof(linea) - 1) { linea[largo++] = c; }
    else { largo = 0; }                    // línea demasiado larga: se descarta
  }
  if (salidasActivas && millis() - ultimaOrden > WATCHDOG_MS) pararTodo();
}
