import netCDF4 as nc  # Импортируем библиотеку для работы с файлами NetCDF
import numpy as np  # Импортируем библиотеку для работы с массивами и научными вычислениями
import pandas as pd  # Импортируем библиотеку для работы с таблицами данных и Excel файлами
import os  # Импортируем библиотеку для работы с файловой системой

# Определяем путь к директории с файлами NetCDF
file_directory = 'C:/'  # Путь к директории с файлами NetCDF
file_prefix = 'file'  # Префикс имен файлов NetCDF
file_suffix = '.nc'  # Суффикс имен файлов NetCDF (расширение файла)

# Определяем координаты городов (широта и долгота)
cities = {
    'Ufa': [54.73, 55.97],  # Координаты города Уфа
    'Sterlitamak': [53.62, 55.95],  # Координаты города Стерлитамак
    'Salavat': [53.37, 55.93],  # Координаты города Салават
    'Tuymazy': [54.6, 53.7],  # Координаты города Туймазы
    'Uchaly': [54.3, 59.4],  # Координаты города Учалы
    'Beloretsk': [53.97, 58.4]  # Координаты города Белорецк
}

# Функция для нахождения ближайших индексов координат
def find_nearest_index(lon, lat, city_coords):
    lon_idx = np.argmin(np.abs(lon - city_coords[1]))  # Находим индекс ближайшей долготы
    lat_idx = np.argmin(np.abs(lat - city_coords[0]))  # Находим индекс ближайшей широты
    return lon_idx, lat_idx  # Возвращаем найденные индексы

# Функция для загрузки данных из файла NetCDF
def load_nc_data(ncfile):
    try:
        dataset = nc.Dataset(ncfile, 'r')  # Открываем файл NetCDF для чтения
        time = dataset.variables['time'][:]  # Загружаем переменную времени
        levels = dataset.variables['lev'][:]  # Загружаем уровни высоты
        lon = dataset.variables['lon'][:]  # Загружаем данные по долготе
        lat = dataset.variables['lat'][:]  # Загружаем данные по широте
        hno3 = dataset.variables['hno3'][:]  # Загружаем данные по концентрации HNO3
        dataset.close()  # Закрываем файл после загрузки данных
        return time, levels, lon, lat, hno3  # Возвращаем загруженные данные
    except FileNotFoundError:  # Обработка случая, если файл не найден
        print(f"Файл не найден: {ncfile}")  # Выводим сообщение об ошибке
        return None, None, None, None, None  # Возвращаем None, если файл не найден
    except Exception as e:  # Обработка всех других исключений
        print(f"Ошибка при загрузке файла {ncfile}: {e}")  # Выводим сообщение об ошибке
        return None, None, None, None, None  # Возвращаем None в случае ошибки

# Основная функция
def main():
    # Определяем директорию для сохранения выходных данных
    output_directory = 'C:/temp/'  # Путь к директории для сохранения выходных файлов
    if not os.path.exists(output_directory):  # Проверяем, существует ли директория
        os.makedirs(output_directory)  # Создаем директорию, если она не существует

    # Инициализируем список для хранения всех данных
    all_data = []  # Список для накопления всех записей данных

    # Составляем список файлов NetCDF (от file.nc до file11.nc)
    file_names = [f'{file_directory}{file_prefix}.nc'] + [f'{file_directory}{file_prefix}{i}{file_suffix}' for i in range(1, 12)]
    # Пример: ['C:/file.nc', 'C:/file1.nc', ..., 'C:/file11.nc']

    # Проходим по каждому файлу в списке
    for file_index, ncfile in enumerate(file_names):
        # Загружаем данные из файла NetCDF
        time, levels, lon, lat, hno3 = load_nc_data(ncfile)

        # Если данные не загрузились, пропускаем этот файл
        if time is None:
            continue  # Переходим к следующему файлу

        # Определяем год на основе индекса файла (начиная с 2010 года)
        year = 2010 + file_index  # Пример: первый файл - 2010, второй - 2011 и т.д.

        # Проходим по каждому городу в списке
        for city_name, city_coords in cities.items():
            lon_idx, lat_idx = find_nearest_index(lon, lat, city_coords)  # Находим индексы для города

            # Проходим по каждому месяцу и уровню высоты
            for month in range(12):  # Месяцы от 0 до 11
                for level in range(27):  # Уровни от 0 до 26
                    value = hno3[month, level, lat_idx, lon_idx]  # Извлекаем данные для конкретного месяца и уровня

                    # Проверяем, маскируются ли данные (например, пропущенные значения) и заменяем их на 0
                    if np.ma.is_masked(value):
                        final_value = 0.0  # Если значение маскировано, устанавливаем 0
                    else:
                        final_value = value / 1000.0  # Преобразуем значения, деля на 1000

                    # Добавляем запись в список
                    all_data.append({
                        'City': city_name,  # Название города
                        'Level': level + 1,  # Уровень высоты (начиная с 1)
                        'Year': year,  # Год
                        'Month': month + 1,  # Месяц (начиная с 1)
                        'HNO3_Concentration': final_value  # Концентрация HNO3
                    })

    # Создаем DataFrame из собранных данных
    df_all = pd.DataFrame(all_data)  # Преобразуем список словарей в DataFrame

    # Определяем порядок столбцов
    df_all = df_all[['City', 'Level', 'Year', 'Month', 'HNO3_Concentration']]  # Упорядочиваем столбцы

    # Сохраняем данные в один Excel файл с одним листом
    output_filename = os.path.join(output_directory, 'all_cities_data_combined.xlsx')  # Формируем путь к выходному файлу
    df_all.to_excel(output_filename, index=False, engine='openpyxl')  # Записываем DataFrame в Excel без индексов

    print(f"Данные успешно сохранены в {output_filename}")  # Выводим сообщение об успешном сохранении

# Проверяем, выполняется ли скрипт напрямую
if __name__ == "__main__":
    main()  # Вызов основной функции для обработки данных