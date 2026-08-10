import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from datetime import datetime
from zoneinfo import ZoneInfo
import re

ZONA_HORARIA_MX = ZoneInfo('America/Mexico_City')
def obtener_fecha_hora_mx():
    return datetime.now(ZONA_HORARIA_MX)

try:
    from flask_compress import Compress
    compress_disponible = True
except ImportError:
    compress_disponible = False

app = Flask(__name__)
app.secret_key = 'aquatiza_secure_master_key'

if compress_disponible:
    Compress(app)

def obtener_conexion():
    try:
        return mysql.connector.connect(
            host=os.environ.get('DB_HOST', 'mysql-3ab14a49-aquatiza.aivencloud.com'),
            user=os.environ.get('DB_USER', 'avnadmin'),
            password=os.environ.get('DB_PASSWORD', 'AVNS_YaPZ5FIFC52_ib0mVxE'),
            database=os.environ.get('DB_NAME', 'defaultdb'),
            port=int(os.environ.get('DB_PORT', 28303)),
            ssl_disabled=False
        )
    except mysql.connector.Error as error:
        return None

@app.route('/')
def login_vista():
    return render_template('login.html', mensaje_error=None)

@app.route('/ingresar', methods=['GET', 'POST'])
def login_procesar():
    if request.method == 'GET':
        return redirect(url_for('login_vista'))
    txt_usuario = request.form['input_usuario'].strip()
    txt_password = request.form['input_password'].strip()
    conexion = obtener_conexion()
    if conexion is None:
        return render_template('login.html', mensaje_error="Error al conectar con la base de datos.")
    try:
        cursor = conexion.cursor(dictionary=True)
        query = "SELECT id_usuario, nom_usuario, contraseña, rol FROM Usuario WHERE nom_usuario = %s"
        cursor.execute(query, (txt_usuario,))
        usuario = cursor.fetchone()
        if usuario and check_password_hash(usuario['contraseña'], txt_password):
            session['id_usuario'] = usuario['id_usuario']
            session['nombre'] = usuario['nom_usuario']
            session['rol'] = usuario['rol'].lower()
            if session['rol'] in ["dueño", "administrador"]:
                return redirect(url_for('inventario_dashboard'))
            else:
                return redirect(url_for('control_rutas_empleado'))
        else:
            return render_template('login.html', mensaje_error="Usuario o contraseña incorrectos.")
    except mysql.connector.Error as e:
        return render_template('login.html', mensaje_error=f"Error: {e}")
    finally:
        cursor.close()
        conexion.close()

@app.route('/inventario')
def inventario_dashboard():
    if 'id_usuario' not in session or session['rol'] not in ["dueño", "administrador"]:
        return redirect(url_for('login_vista'))
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT IFNULL(SUM(ganancia), 0) AS total_ing FROM Movimiento WHERE estado_bucle = 'Terminado'")
    ingresos_totales = cursor.fetchone()['total_ing']
    cursor.execute("SELECT IFNULL(SUM(monto), 0) AS total_egr FROM Gastos")
    egresos_totales = cursor.fetchone()['total_egr']
    ganancia_real = ingresos_totales - egresos_totales
    cursor.execute("SELECT tipo_garrafon, cant_total, u_actualizacion FROM Inventario")
    filas = cursor.fetchall()
    inv = {'stock_garrafon_20':0, 'stock_garrafon_5':0, 'stock_tapas':0, 'stock_sellos':0, 'stock_mermas':0, 'act':''}
    fecha_mas_reciente = None
    for f in filas:
        tipo = f['tipo_garrafon'].lower()
        if f['u_actualizacion']:
            if fecha_mas_reciente is None or f['u_actualizacion'] > fecha_mas_reciente:
                fecha_mas_reciente = f['u_actualizacion']
        if '20l' in tipo: inv['stock_garrafon_20'] = f['cant_total']
        elif '5l' in tipo: inv['stock_garrafon_5'] = f['cant_total']
        elif 'tapas' in tipo: inv['stock_tapas'] = f['cant_total']
        elif 'sellos' in tipo: inv['stock_sellos'] = f['cant_total']
        elif 'merma' in tipo: inv['stock_mermas'] = f['cant_total']
    if fecha_mas_reciente:
        inv['act'] = fecha_mas_reciente.strftime('%d/%m/%y %I:%M %p')
    hoy = obtener_fecha_hora_mx().strftime('%Y-%m-%d')
    cursor.execute("SELECT IFNULL(SUM(ganancia), 0) AS ingresos FROM Movimiento WHERE DATE(fecha_hora) = %s AND estado_bucle = 'Terminado'", (hoy,))
    ingresos_hoy = cursor.fetchone()['ingresos']
    cursor.execute("SELECT IFNULL(SUM(monto), 0) AS egresos FROM Gastos WHERE fecha = %s", (hoy,))
    egresos_hoy = cursor.fetchone()['egresos']
    cursor.execute("SELECT IFNULL(SUM(cant_mermas), 0) AS mermas FROM Historial_mermas WHERE DATE(fecha_hora) = %s", (hoy,))
    mermas_hoy = cursor.fetchone()['mermas']
    cursor.execute("SELECT id_usuario, nom_usuario, contraseña, rol FROM Usuario")
    lista_usuarios = cursor.fetchall()
    
    # Historial completo de gastos para la lista interactiva
    cursor.execute("SELECT id_gasto, concepto, monto, fecha FROM Gastos ORDER BY fecha DESC, id_gasto DESC")
    historial_gastos = cursor.fetchall()

    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    gastos_agrupados = []
    desglose_ventas = {'llenados_20': 0, 'llenados_5': 0, 'total_envases': 0, 'total_mermas': 0}
    if desde and hasta:
        cursor.execute("SELECT IFNULL(SUM(ganancia), 0) AS ing FROM Movimiento WHERE DATE(fecha_hora) BETWEEN %s AND %s AND estado_bucle = 'Terminado'", (desde, hasta))
        ingresos_hist = cursor.fetchone()['ing']
        cursor.execute("SELECT IFNULL(SUM(monto), 0) AS egr FROM Gastos WHERE fecha BETWEEN %s AND %s", (desde, hasta))
        egresos_hist = cursor.fetchone()['egr']
        cursor.execute("SELECT concepto, SUM(monto) AS total_gasto FROM Gastos WHERE fecha BETWEEN %s AND %s GROUP BY concepto", (desde, hasta))
        gastos_agrupados = cursor.fetchall()
        cursor.execute("""
            SELECT
                SUM(CASE WHEN i.tipo_garrafon LIKE '%20L%' THEN m.g_regreso_vacios ELSE 0 END) AS llenados_20,
                SUM(CASE WHEN i.tipo_garrafon LIKE '%5L%' THEN m.g_regreso_vacios ELSE 0 END) AS llenados_5,
                SUM(m.g_envases_vendidos) AS envases
            FROM Movimiento m
            JOIN Inventario i ON m.id_inventario_fk = i.id_inventario
            WHERE DATE(m.fecha_hora) BETWEEN %s AND %s AND m.estado_bucle = 'Terminado'
        """, (desde, hasta))
        vtas = cursor.fetchone()
        cursor.execute("SELECT IFNULL(SUM(cant_mermas), 0) AS mermas FROM Historial_mermas WHERE DATE(fecha_hora) BETWEEN %s AND %s", (desde, hasta))
        mermas_hist = cursor.fetchone()['mermas']
        desglose_ventas = {
            'llenados_20': vtas['llenados_20'] if vtas['llenados_20'] else 0,
            'llenados_5': vtas['llenados_5'] if vtas['llenados_5'] else 0,
            'total_envases': vtas['envases'] if vtas['envases'] else 0,
            'total_mermas': mermas_hist
        }
    else:
        cursor.execute("SELECT IFNULL(SUM(ganancia), 0) AS ing FROM Movimiento WHERE estado_bucle = 'Terminado'")
        ingresos_hist = cursor.fetchone()['ing']
        cursor.execute("SELECT IFNULL(SUM(monto), 0) AS egr FROM Gastos")
        egresos_hist = cursor.fetchone()['egr']
    balance_neto = ingresos_hist - egresos_hist
    cursor.execute("""
        SELECT m.id_movimiento, u.nom_usuario AS empleado, i.tipo_garrafon, m.g_salidas,
               m.g_regreso_vacios, m.g_regreso_llenos, m.g_envases_vendidos, m.ganancia,
               m.tipo_movimiento, m.fecha_hora, m.estado_bucle,
               (SELECT IFNULL(SUM(cant_mermas), 0) FROM Historial_mermas WHERE id_movimiento_fk = m.id_movimiento) AS mermas_ruta
        FROM Movimiento m
        JOIN Usuario u ON m.id_usuario_fk = u.id_usuario
        JOIN Inventario i ON m.id_inventario_fk = i.id_inventario
        ORDER BY m.fecha_hora DESC
    """)
    historial_rutas = cursor.fetchall()
    cursor.execute("""
        SELECT m.id_movimiento, m.id_inventario_fk, m.g_salidas, i.tipo_garrafon
        FROM Movimiento m
        JOIN Inventario i ON m.id_inventario_fk = i.id_inventario
        WHERE m.estado_bucle = 'En Ruta'
    """)
    rutas_activas = cursor.fetchall()
    cursor.close()
    conexion.close()
    return render_template('inventario.html',
                           nombre=session['nombre'], inv=inv, ganancia_real=ganancia_real,
                           ingresos_hoy=ingresos_hoy, egresos_hoy=egresos_hoy, mermas_hoy=mermas_hoy,
                           usuarios=lista_usuarios, ingresos_hist=ingresos_hist, egresos_hist=egresos_hist,
                           balance_neto=balance_neto, desde=desde, hasta=hasta,
                           historial_rutas=historial_rutas, rutas_activas=rutas_activas,
                           gastos_agrupados=gastos_agrupados, desglose_ventas=desglose_ventas,
                           historial_gastos=historial_gastos)

@app.route('/guardar_inventario', methods=['POST'])
def guardar_inventario():
    if 'id_usuario' not in session: return redirect(url_for('login_vista'))
    stock_20 = request.form.get('stock_garrafon_20', '0')
    stock_5 = request.form.get('stock_garrafon_5', '0')
    tapas = request.form.get('stock_tapas', '0')
    sellos = request.form.get('stock_sellos', '0')
    try:
        if int(stock_20) > 1000 or int(stock_5) > 1000 or int(tapas) > 1000 or int(sellos) > 1000:
            flash("❌ Error: Límite máximo es 1,000 unidades.", "error")
            return redirect(url_for('inventario_dashboard'))
        if int(stock_20) < 0 or int(stock_5) < 0 or int(tapas) < 0 or int(sellos) < 0:
            flash("❌ Error: No se permiten inventarios negativos.", "error")
            return redirect(url_for('inventario_dashboard'))
    except (ValueError, TypeError):
        flash("❌ Error: Las cantidades ingresadas deben ser números válidos.", "error")
        return redirect(url_for('inventario_dashboard'))
    ahora_mx = obtener_fecha_hora_mx().strftime('%Y-%m-%d %H:%M:%S')
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    mapeo = [
        (stock_20, "%20L%"),
        (stock_5, "%5L%"),
        (tapas, "%tapas%"),
        (sellos, "%sellos%")
    ]
    for cantidad, concepto in mapeo:
        cursor.execute("UPDATE Inventario SET cant_total = %s, u_actualizacion = %s WHERE tipo_garrafon LIKE %s", (cantidad, ahora_mx, concepto))
    conexion.commit()
    cursor.close()
    conexion.close()
    flash("📦 Catálogo de inventario actualizado correctamente.", "success")
    return redirect(url_for('inventario_dashboard'))

@app.route('/registrar_gasto', methods=['POST'])
def registrar_gasto():
    if 'id_usuario' not in session: return redirect(url_for('login_vista'))
    concepto = request.form.get('concepto')
    try:
        monto = float(request.form.get('monto', 0.0))
    except (ValueError, TypeError):
        flash("❌ Error: El monto ingresado no es válido.", "error")
        return redirect(url_for('inventario_dashboard', tab='finanzas'))
    if monto <= 0:
        flash("❌ Error: El monto del gasto debe ser mayor a 0.", "error")
        return redirect(url_for('inventario_dashboard', tab='finanzas'))
    LIMITE_MAXIMO_GASTO = 10000.0
    if monto > LIMITE_MAXIMO_GASTO:
        flash(f"❌ Error: No se permiten gastos superiores a ${LIMITE_MAXIMO_GASTO:,.2f}.", "error")
        return redirect(url_for('inventario_dashboard', tab='finanzas'))
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT IFNULL(SUM(ganancia), 0) AS total_ing FROM Movimiento WHERE estado_bucle = 'Terminado'")
    ingresos_totales = cursor.fetchone()['total_ing']
    cursor.execute("SELECT IFNULL(SUM(monto), 0) AS total_egr FROM Gastos")
    egresos_totales = cursor.fetchone()['total_egr']
    caja_real = ingresos_totales - egresos_totales
    if monto > caja_real:
        cursor.close()
        conexion.close()
        flash(f"❌ Error: El gasto de ${monto:,.2f} supera el saldo disponible en caja real (${caja_real:,.2f}).", "error")
        return redirect(url_for('inventario_dashboard', tab='finanzas'))
    fecha = request.form.get('fecha')
    cursor.execute("INSERT INTO Gastos (concepto, monto, fecha, id_usuario_fk) VALUES (%s, %s, %s, %s)",
                   (concepto, monto, fecha, session['id_usuario']))
    conexion.commit()
    cursor.close()
    conexion.close()
    flash("💸 Gasto registrado correctamente en el sistema.", "success")
    return redirect(url_for('inventario_dashboard', tab='finanzas'))

@app.route('/eliminar_gasto', methods=['POST'])
def eliminar_gasto():
    if 'id_usuario' not in session or session['rol'] not in ["dueño", "administrador"]:
        return redirect(url_for('login_vista'))
    id_gasto = request.form.get('id_gasto')
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT monto FROM Gastos WHERE id_gasto = %s", (id_gasto,))
    gasto = cursor.fetchone()
    if gasto:
        cursor.execute("DELETE FROM Gastos WHERE id_gasto = %s", (id_gasto,))
        conexion.commit()
        flash("✅ Gasto eliminado. El monto fue devuelto al balance de caja.", "success")
    else:
        flash("❌ El gasto que intenta eliminar no existe.", "error")
    cursor.close()
    conexion.close()
    return redirect(url_for('inventario_dashboard', tab='finanzas'))

@app.route('/gestion_usuario', methods=['POST'])
def gestion_usuario():
    if 'id_usuario' not in session: return redirect(url_for('login_vista'))
    accion = request.form.get('accion')
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    if accion == "agregar":
        usuario = request.form['usuario'].strip()
        pwd = request.form['password'].strip()
        rol = request.form['rol']
        if not re.match(r'^[A-Za-záéíóúÁÉÍÓÚñÑ]+( [A-Za-záéíóúÁÉÍÓÚñÑ]+)?$', usuario):
            flash("❌ Error: El usuario solo puede contener 1 o 2 nombres (solo letras).", "error")
            cursor.close()
            conexion.close()
            return redirect(url_for('inventario_dashboard'))
        if not re.match(r'^[A-Za-z0-9]{6,10}$', pwd):
            flash("❌ Error: La contraseña debe tener entre 6 y 10 caracteres, sin espacios ni caracteres especiales.", "error")
            cursor.close()
            conexion.close()
            return redirect(url_for('inventario_dashboard'))
        cursor.execute("SELECT id_usuario FROM Usuario WHERE nom_usuario = %s", (usuario,))
        usuario_existente = cursor.fetchone()
        if usuario_existente:
            flash("❌ Error: El usuario ya está registrado.", "error")
            cursor.close()
            conexion.close()
            return redirect(url_for('inventario_dashboard'))
        pwd_encriptada = generate_password_hash(pwd)
        cursor.execute("INSERT INTO Usuario (nom_usuario, contraseña, rol) VALUES (%s, %s, %s)", (usuario, pwd_encriptada, rol))
        flash(f"👤 Usuario '{usuario}' agregado con éxito.", "success")
    elif accion == "cambiar_pass":
        id_usuario_target = request.form.get('id_usuario')
        nueva_pwd = request.form.get('nueva_password', '').strip()
        if not re.match(r'^[A-Za-z0-9]{6,10}$', nueva_pwd):
            flash("❌ Error: La contraseña debe tener entre 6 y 10 caracteres, sin espacios ni caracteres especiales.", "error")
            cursor.close()
            conexion.close()
            return redirect(url_for('inventario_dashboard'))
        nueva_pwd_encriptada = generate_password_hash(nueva_pwd)
        cursor.execute("UPDATE Usuario SET contraseña = %s WHERE id_usuario = %s", (nueva_pwd_encriptada, id_usuario_target))
        flash("🔑 Contraseña actualizada correctamente.", "success")
    conexion.commit()
    cursor.close()
    conexion.close()
    return redirect(url_for('inventario_dashboard'))

@app.route('/eliminar_usuario', methods=['POST'])
def eliminar_usuario():
    if 'id_usuario' not in session: return redirect(url_for('login_vista'))
    id_usuario_target = request.form.get('id_usuario')
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) AS total FROM Movimiento WHERE id_usuario_fk = %s", (id_usuario_target,))
    movs = cursor.fetchone()['total']
    if movs > 0:
        flash("❌ No se puede eliminar el usuario porque tiene registros asociados.", "error")
    else:
        cursor.execute("DELETE FROM Usuario WHERE id_usuario = %s", (id_usuario_target,))
        conexion.commit()
        flash("✅ Usuario eliminado correctamente.", "success")
    cursor.close()
    conexion.close()
    return redirect(url_for('inventario_dashboard'))

@app.route('/eliminar_ruta', methods=['POST'])
def eliminar_ruta():
    if 'id_usuario' not in session or session['rol'] not in ["dueño", "administrador"]:
        return redirect(url_for('login_vista'))
    id_mov = request.form.get('id_movimiento')
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    
    # 1. Obtener datos de la ruta antes de borrar para hacer el rollback
    cursor.execute("SELECT * FROM Movimiento WHERE id_movimiento = %s", (id_mov,))
    mov = cursor.fetchone()
    
    if mov:
        id_inv = mov['id_inventario_fk']
        v_vacios = mov['g_regreso_vacios'] or 0
        v_envases = mov['g_envases_vendidos'] or 0
        v_salidas = mov['g_salidas'] or 0
        
        cursor.execute("SELECT IFNULL(SUM(cant_mermas), 0) AS total_mermas FROM Historial_mermas WHERE id_movimiento_fk = %s", (id_mov,))
        mermas_ruta = cursor.fetchone()['total_mermas']
        
        if mov['estado_bucle'] == 'Terminado':
            # Restauración de stock de garrafones (regresan los envases vendidos + mermas)
            garrafones_a_devolver = v_envases + mermas_ruta
            if garrafones_a_devolver > 0:
                cursor.execute("UPDATE Inventario SET cant_total = cant_total + %s WHERE id_inventario = %s", (garrafones_a_devolver, id_inv))
            
            # Restauración de insumos invisibles (tapas y sellos que se consumieron en la venta)
            insumos_a_devolver = v_vacios + v_envases
            if insumos_a_devolver > 0:
                cursor.execute("UPDATE Inventario SET cant_total = cant_total + %s WHERE tipo_garrafon LIKE '%tapas%'", (insumos_a_devolver,))
                cursor.execute("UPDATE Inventario SET cant_total = cant_total + %s WHERE tipo_garrafon LIKE '%sellos%'", (insumos_a_devolver,))
            
            # Restar mermas globales generadas por esta ruta
            if mermas_ruta > 0:
                cursor.execute("UPDATE Inventario SET cant_total = GREATEST(0, cant_total - %s) WHERE tipo_garrafon LIKE '%merma%'", (mermas_ruta,))
        else:
            # Si estaba 'En Ruta', simplemente se devuelven todos los garrafones que salieron
            cursor.execute("UPDATE Inventario SET cant_total = cant_total + %s WHERE id_inventario = %s", (v_salidas, id_inv))

        # 2. Proceder con el borrado físico
        cursor.execute("DELETE FROM Historial_mermas WHERE id_movimiento_fk = %s", (id_mov,))
        cursor.execute("DELETE FROM Movimiento WHERE id_movimiento = %s", (id_mov,))
        conexion.commit()
        flash("✅ Ruta eliminada. Stock, insumos y caja restablecidos al estado previo.", "success")
    else:
        flash("❌ La ruta no fue encontrada.", "error")
        
    cursor.close()
    conexion.close()
    return redirect(url_for('inventario_dashboard', tab='rutas'))

@app.route('/ruta_salida', methods=['POST'])
def ruta_salida():
    if 'id_usuario' not in session: return redirect(url_for('login_vista'))
    id_usuario = session['id_usuario']
    tipo_mov = request.form['tipo_entrega']
    destino_redireccion = url_for('inventario_dashboard') if session['rol'] in ["dueño", "administrador"] else url_for('control_rutas_empleado')
    try:
        cant_20 = int(request.form.get('cantidad_20', 0))
        cant_5 = int(request.form.get('cantidad_5', 0))
    except ValueError:
        flash("❌ Error: Las cantidades ingresadas deben ser números enteros válidos.", "error")
        return redirect(destino_redireccion)
    if cant_20 < 0 or cant_5 < 0:
        flash("❌ Error: No se permiten cantidades negativas.", "error")
        return redirect(destino_redireccion)
    if cant_20 == 0 and cant_5 == 0:
        flash("❌ Error: Debe ingresar una cantidad mayor a 0 para al menos un tipo de garrafón.", "error")
        return redirect(destino_redireccion)
    if cant_20 > 50 or cant_5 > 50:
        flash("❌ Error: El límite máximo permitido es de 50 garrafones por viaje.", "error")
        return redirect(destino_redireccion)
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    if cant_20 > 0:
        cursor.execute("SELECT id_inventario, cant_total FROM Inventario WHERE tipo_garrafon LIKE '%20L%'")
        inv_20 = cursor.fetchone()
        if not inv_20 or cant_20 > inv_20['cant_total']:
            cursor.close()
            conexion.close()
            flash("❌ Error: Stock insuficiente para garrafones de 20L.", "error")
            return redirect(destino_redireccion)
    if cant_5 > 0:
        cursor.execute("SELECT id_inventario, cant_total FROM Inventario WHERE tipo_garrafon LIKE '%5L%'")
        inv_5 = cursor.fetchone()
        if not inv_5 or cant_5 > inv_5['cant_total']:
            cursor.close()
            conexion.close()
            flash("❌ Error: Stock insuficiente para garrafones de 5L.", "error")
            return redirect(destino_redireccion)
    ahora_mx = obtener_fecha_hora_mx().strftime('%Y-%m-%d %H:%M:%S')
    if cant_20 > 0:
        cursor.execute("UPDATE Inventario SET cant_total = cant_total - %s WHERE id_inventario = %s", (cant_20, inv_20['id_inventario']))
        cursor.execute("""
            INSERT INTO Movimiento (g_salidas, g_regreso_vacios, g_regreso_llenos, g_envases_vendidos, ganancia, tipo_movimiento, fecha_hora, id_usuario_fk, id_inventario_fk, estado_bucle)
            VALUES (%s, 0, 0, 0, 0.00, %s, %s, %s, %s, 'En Ruta')
        """, (cant_20, tipo_mov, ahora_mx, id_usuario, inv_20['id_inventario']))
    if cant_5 > 0:
        cursor.execute("UPDATE Inventario SET cant_total = cant_total - %s WHERE id_inventario = %s", (cant_5, inv_5['id_inventario']))
        cursor.execute("""
            INSERT INTO Movimiento (g_salidas, g_regreso_vacios, g_regreso_llenos, g_envases_vendidos, ganancia, tipo_movimiento, fecha_hora, id_usuario_fk, id_inventario_fk, estado_bucle)
            VALUES (%s, 0, 0, 0, 0.00, %s, %s, %s, %s, 'En Ruta')
        """, (cant_5, tipo_mov, ahora_mx, id_usuario, inv_5['id_inventario']))
    conexion.commit()
    cursor.close()
    conexion.close()
    flash("🚚 Salida registrada. Inventario descontado con éxito.", "success")
    return redirect(destino_redireccion)

@app.route('/ruta_regreso', methods=['POST'])
def ruta_regreso():
    if 'id_usuario' not in session: return redirect(url_for('login_vista'))
    destino = url_for('inventario_dashboard') if session['rol'] in ["dueño", "administrador"] else url_for('control_rutas_empleado')
    conexion = obtener_conexion()
    if conexion is None:
        flash("❌ Error de conexión a la base de datos.", "error")
        return redirect(destino)
    cursor = conexion.cursor(dictionary=True)
    if session['rol'] in ["dueño", "administrador"]:
        cursor.execute("SELECT id_movimiento, id_inventario_fk, g_salidas FROM Movimiento WHERE estado_bucle = 'En Ruta'")
    else:
        cursor.execute("SELECT id_movimiento, id_inventario_fk, g_salidas FROM Movimiento WHERE id_usuario_fk = %s AND estado_bucle = 'En Ruta'", (session['id_usuario'],))
    rutas_activas = cursor.fetchall()
    if not rutas_activas:
        flash("⚠️ No se encontraron rutas activas pendientes por procesar.", "error")
        cursor.close()
        conexion.close()
        return redirect(destino)
    movimientos_cerrados = 0
    ahora_mx = obtener_fecha_hora_mx().strftime('%Y-%m-%d %H:%M:%S')
    for ruta in rutas_activas:
        id_mov = str(ruta['id_movimiento'])
        llenos_raw = request.form.get(f'regreso_llenos_{id_mov}') or request.form.get('regreso_llenos')
        if llenos_raw is None:
            continue
        try:
            vacios_raw = request.form.get(f'regreso_vacios_{id_mov}') or request.form.get('regreso_vacios', 0)
            envases_raw = request.form.get(f'envases_vendidos_{id_mov}') or request.form.get('envases_vendidos', 0)
            mermas_raw = request.form.get(f'mermas_{id_mov}') or request.form.get('mermas', 0)
            llenos = int(llenos_raw)
            vacios = int(vacios_raw)
            envases = int(envases_raw)
            mermas = int(mermas_raw)
        except (ValueError, TypeError):
            flash("❌ Error: Ingrese valores numéricos enteros válidos.", "error")
            cursor.close()
            conexion.close()
            return redirect(destino)
        if llenos < 0 or vacios < 0 or envases < 0 or mermas < 0:
            flash("❌ Error: No se permiten números negativos en el retorno de ruta.", "error")
            cursor.close()
            conexion.close()
            return redirect(destino)
        g_salidas = int(ruta['g_salidas'])
        total_retorno = llenos + vacios + envases + mermas
        if total_retorno != g_salidas:
            diferencia = g_salidas - total_retorno
            if diferencia > 0:
                flash(f"❌ ERROR DE CUADRE: Salieron {g_salidas} garrafones y estás intentando registrar {total_retorno}. Te FALTAN {diferencia} garrafones por justificar.", "error")
            else:
                flash(f"❌ ERROR DE CUADRE: Salieron {g_salidas} garrafones y estás intentando registrar {total_retorno}. Te SOBRAN {abs(diferencia)} garrafones.", "error")
            cursor.close()
            conexion.close()
            return redirect(destino)
        id_inv = ruta['id_inventario_fk']
        cursor.execute("SELECT precio_llenado, precio_envase FROM Inventario WHERE id_inventario = %s", (id_inv,))
        precios = cursor.fetchone()
        p_llenado = float(precios['precio_llenado']) if precios and precios['precio_llenado'] else 0.0
        p_envase = float(precios['precio_envase']) if precios and precios['precio_envase'] else 0.0
        ganancia = (vacios * p_llenado) + (envases * p_envase)
        retorno_total = llenos + vacios
        if retorno_total > 0:
            cursor.execute("UPDATE Inventario SET cant_total = cant_total + %s WHERE id_inventario = %s", (retorno_total, id_inv))
        
        # Descontar tapas y sellos invisibles según ventas totales de esta ruta (llenados + envases)
        insumos_usados = vacios + envases
        if insumos_usados > 0:
            cursor.execute("UPDATE Inventario SET cant_total = GREATEST(0, cant_total - %s) WHERE tipo_garrafon LIKE '%tapas%'", (insumos_usados,))
            cursor.execute("UPDATE Inventario SET cant_total = GREATEST(0, cant_total - %s) WHERE tipo_garrafon LIKE '%sellos%'", (insumos_usados,))
            
        if mermas > 0:
            cursor.execute("UPDATE Inventario SET cant_total = cant_total + %s WHERE tipo_garrafon LIKE '%merma%'", (mermas,))
            cursor.execute("INSERT INTO Historial_mermas (cant_mermas, tipo_mermas, fecha_hora, id_movimiento_fk) VALUES (%s, 'Mermas de Ruta', %s, %s)", (mermas, ahora_mx, id_mov))
        cursor.execute("""
            UPDATE Movimiento
            SET g_regreso_vacios = %s, g_regreso_llenos = %s, g_envases_vendidos = %s, ganancia = %s, estado_bucle = 'Terminado'
            WHERE id_movimiento = %s
        """, (vacios, llenos, envases, ganancia, id_mov))
        movimientos_cerrados += 1
    conexion.commit()
    cursor.close()
    conexion.close()
    if movimientos_cerrados > 0:
        flash("✅ Retorno de ruta registrado con éxito. Caja e inventario actualizados.", "success")
    return redirect(destino)

@app.route('/control_rutas')
def control_rutas_empleado():
    if 'id_usuario' not in session: return redirect(url_for('login_vista'))
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT IFNULL(SUM(ganancia), 0) AS total_ing FROM Movimiento WHERE estado_bucle = 'Terminado'")
    ingresos = cursor.fetchone()['total_ing']
    cursor.execute("SELECT IFNULL(SUM(monto), 0) AS total_egr FROM Gastos")
    egresos = cursor.fetchone()['total_egr']
    ganancia_real = ingresos - egresos
    cursor.execute("""
        SELECT m.id_movimiento, m.id_inventario_fk, m.g_salidas, i.tipo_garrafon
        FROM Movimiento m
        JOIN Inventario i ON m.id_inventario_fk = i.id_inventario
        WHERE m.id_usuario_fk = %s AND m.estado_bucle = 'En Ruta'
    """, (session['id_usuario'],))
    rutas_activas = cursor.fetchall()
    cursor.close()
    conexion.close()
    return render_template('control_rutas.html', nombre=session['nombre'], rutas_activas=rutas_activas, ganancia_real=ganancia_real)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_vista'))

@app.route('/descargar_reporte')
def descargar_reporte():
    if 'id_usuario' not in session or session['rol'] not in ["dueño", "administrador"]:
        return redirect(url_for('login_vista'))
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    if desde and hasta:
        cursor.execute("SELECT IFNULL(SUM(ganancia), 0) AS ing FROM Movimiento WHERE DATE(fecha_hora) BETWEEN %s AND %s AND estado_bucle = 'Terminado'", (desde, hasta))
        ingresos_hist = cursor.fetchone()['ing']
        cursor.execute("SELECT IFNULL(SUM(monto), 0) AS egr FROM Gastos WHERE fecha BETWEEN %s AND %s", (desde, hasta))
        egresos_hist = cursor.fetchone()['egr']
        cursor.execute("SELECT fecha, concepto, monto FROM Gastos WHERE fecha BETWEEN %s AND %s ORDER BY fecha DESC", (desde, hasta))
        gastos = cursor.fetchall()
        cursor.execute("""
            SELECT
                SUM(CASE WHEN i.tipo_garrafon LIKE '%20L%' THEN m.g_regreso_vacios ELSE 0 END) AS llenados_20,
                SUM(CASE WHEN i.tipo_garrafon LIKE '%5L%' THEN m.g_regreso_vacios ELSE 0 END) AS llenados_5,
                SUM(m.g_envases_vendidos) AS envases
            FROM Movimiento m
            JOIN Inventario i ON m.id_inventario_fk = i.id_inventario
            WHERE DATE(m.fecha_hora) BETWEEN %s AND %s AND m.estado_bucle = 'Terminado'
        """, (desde, hasta))
        vtas = cursor.fetchone()
        cursor.execute("SELECT IFNULL(SUM(cant_mermas), 0) AS mermas FROM Historial_mermas WHERE DATE(fecha_hora) BETWEEN %s AND %s", (desde, hasta))
        mermas_hist = cursor.fetchone()['mermas']
        cursor.execute("""
            SELECT m.fecha_hora, u.nom_usuario AS empleado, i.tipo_garrafon, m.g_salidas,
                   m.g_regreso_vacios, m.g_regreso_llenos, m.g_envases_vendidos, m.ganancia,
                   (SELECT IFNULL(SUM(cant_mermas), 0) FROM Historial_mermas WHERE id_movimiento_fk = m.id_movimiento) AS mermas_ruta
            FROM Movimiento m
            JOIN Usuario u ON m.id_usuario_fk = u.id_usuario
            JOIN Inventario i ON m.id_inventario_fk = i.id_inventario
            WHERE DATE(m.fecha_hora) BETWEEN %s AND %s
            ORDER BY m.fecha_hora DESC
        """, (desde, hasta))
        movimientos = cursor.fetchall()
    else:
        cursor.execute("SELECT IFNULL(SUM(ganancia), 0) AS ing FROM Movimiento WHERE estado_bucle = 'Terminado'")
        ingresos_hist = cursor.fetchone()['ing']
        cursor.execute("SELECT IFNULL(SUM(monto), 0) AS egr FROM Gastos")
        egresos_hist = cursor.fetchone()['egr']
        cursor.execute("SELECT fecha, concepto, monto FROM Gastos ORDER BY fecha DESC")
        gastos = cursor.fetchall()
        cursor.execute("""
            SELECT
                SUM(CASE WHEN i.tipo_garrafon LIKE '%20L%' THEN m.g_regreso_vacios ELSE 0 END) AS llenados_20,
                SUM(CASE WHEN i.tipo_garrafon LIKE '%5L%' THEN m.g_regreso_vacios ELSE 0 END) AS llenados_5,
                SUM(m.g_envases_vendidos) AS envases
            FROM Movimiento m
            JOIN Inventario i ON m.id_inventario_fk = i.id_inventario
            WHERE m.estado_bucle = 'Terminado'
        """)
        vtas = cursor.fetchone()
        cursor.execute("SELECT IFNULL(SUM(cant_mermas), 0) AS mermas FROM Historial_mermas")
        mermas_hist = cursor.fetchone()['mermas']
        cursor.execute("""
            SELECT m.fecha_hora, u.nom_usuario AS empleado, i.tipo_garrafon, m.g_salidas,
                   m.g_regreso_vacios, m.g_regreso_llenos, m.g_envases_vendidos, m.ganancia,
                   (SELECT IFNULL(SUM(cant_mermas), 0) FROM Historial_mermas WHERE id_movimiento_fk = m.id_movimiento) AS mermas_ruta
            FROM Movimiento m
            JOIN Usuario u ON m.id_usuario_fk = u.id_usuario
            JOIN Inventario i ON m.id_inventario_fk = i.id_inventario
            ORDER BY m.fecha_hora DESC
        """)
        movimientos = cursor.fetchall()
    balance_neto = ingresos_hist - egresos_hist
    cursor.close()
    conexion.close()
    csv_data = "\ufeff"
    periodo = f"{desde} a {hasta}" if (desde and hasta) else "Historico Completo"
    csv_data += f"REPORTE DE CONTROL DE RUTAS E INVENTARIO ({periodo})\n\n"
    csv_data += "RESUMEN FINANCIERO\n"
    csv_data += f"Total Ingresos (Rutas),${ingresos_hist:.2f}\n"
    csv_data += f"Total Egresos (Gastos),${egresos_hist:.2f}\n"
    csv_data += f"Balance Neto,${balance_neto:.2f}\n\n"
    csv_data += "DESGLOSE DE VENTAS Y MERMAS (CANTIDADES TOTALES)\n"
    csv_data += f"Llenados 20L,{vtas['llenados_20'] if vtas['llenados_20'] else 0} pzs\n"
    csv_data += f"Llenados 5L,{vtas['llenados_5'] if vtas['llenados_5'] else 0} pzs\n"
    csv_data += f"Envases Nuevos Vendidos,{vtas['envases'] if vtas['envases'] else 0} pzs\n"
    csv_data += f"Mermas Totales en Periodo,{mermas_hist if mermas_hist else 0} pzs\n\n"
    csv_data += "DETALLE HISTORIAL DE RUTAS\n"
    csv_data += "Fecha,Empleado,Producto,Salidas (Llenos),Retorno Vacios (Llenados),Retorno Llenos,Envases Vendidos,Mermas Ruta,Ganancia\n"
    for m in movimientos:
        fecha_limpia = m['fecha_hora'].strftime('%d-%m-%Y %H:%M') if m['fecha_hora'] else ''
        csv_data += f" {fecha_limpia},{m['empleado']},{m['tipo_garrafon']},{m['g_salidas']},{m['g_regreso_vacios']},{m['g_regreso_llenos']},{m['g_envases_vendidos']},{m['mermas_ruta']},{m['ganancia']}\n"
    csv_data += "\n"
    csv_data += "DETALLE DE GASTOS\n"
    csv_data += "Fecha,Concepto,Monto\n"
    for g in gastos:
        fecha_gasto = g['fecha'].strftime('%d-%m-%Y') if hasattr(g['fecha'], 'strftime') else str(g['fecha'])
        csv_data += f" {fecha_gasto},{g['concepto']},{g['monto']}\n"
    filename = f"reporte_{desde}_a_{hasta}.csv" if (desde and hasta) else "reporte_general.csv"
    return Response(csv_data, mimetype="text/csv", headers={"Content-disposition": f"attachment; filename={filename}"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)